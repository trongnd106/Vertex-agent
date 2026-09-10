"""Event system and centralized error handling for the routing layer.

Provides:
- ``SystemEvent`` — typed event hierarchy for routing events
- ``EventBus`` — publish/subscribe with type-based routing
- ``CentralizedErrorHandler`` — error categorization and response
- ``CircuitBreaker`` — failure threshold, open/half-open/closed states
- ``RetryHandler`` — configurable retry with backoff
- ``ErrorClassifier`` — classify exceptions into categories
"""

from __future__ import annotations

import asyncio
import enum
import logging
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


# ── Error categories ──────────────────────────────────────────────────


class ErrorCategory(str, enum.Enum):
    """Classification of errors for routing logic."""

    TEMPORARY = "temporary"  # Retryable (network, timeout)
    PERMANENT = "permanent"  # Non-retryable (invalid args, auth)
    BUSINESS = "business"  # Business logic violation
    SYSTEM = "system"  # Internal system error
    UNKNOWN = "unknown"


class ErrorSeverity(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ── System event hierarchy ────────────────────────────────────────────


class EventType(str, enum.Enum):
    """Well-known routing event types."""

    # Routing events
    ROUTE_RESOLVED = "route.resolved"
    ROUTE_FAILED = "route.failed"
    ROUTE_TIMEOUT = "route.timeout"

    # Dispatch events
    TASK_DISPATCHED = "task.dispatched"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"

    # HITL events
    INTERRUPT_RAISED = "hitl.interrupt_raised"
    INTERRUPT_RESOLVED = "hitl.interrupt_resolved"
    APPROVAL_REQUESTED = "hitl.approval_requested"
    APPROVAL_RESOLVED = "hitl.approval_resolved"

    # System events
    CIRCUIT_OPEN = "circuit.open"
    CIRCUIT_HALF_OPEN = "circuit.half_open"
    CIRCUIT_CLOSED = "circuit.closed"
    ERROR_OCCURRED = "error.occurred"

    # Workflow events
    WORKFLOW_STARTED = "workflow.started"
    WORKFLOW_STEP_COMPLETED = "workflow.step_completed"
    WORKFLOW_STEP_FAILED = "workflow.step_failed"
    WORKFLOW_COMPLETED = "workflow.completed"
    WORKFLOW_FAILED = "workflow.failed"


@dataclass
class SystemEvent:
    """Base event in the routing event system.

    Attributes:
        event_type: The ``EventType`` of this event.
        source: Identifier of the component that emitted it.
        payload: Event-specific data.
        timestamp: When the event was created.
        event_id: Unique identifier.
    """

    event_type: EventType = EventType.ROUTE_RESOLVED
    source: str = ""
    payload: Any = None
    timestamp: float = 0.0
    event_id: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = time.time()
        if not self.event_id:
            self.event_id = str(uuid.uuid4())

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "source": self.source,
            "payload": self.payload,
            "timestamp": self.timestamp,
        }


# ── Event bus ─────────────────────────────────────────────────────────

EventHandler = Callable[[SystemEvent], Awaitable[None]]


class EventBus:
    """Typed publish/subscribe event bus for routing events.

    Supports type-based subscription: a handler registered for
    ``EventType.ROUTE_RESOLVED`` receives only that event type.
    """

    def __init__(self) -> None:
        self._handlers: dict[EventType, list[EventHandler]] = defaultdict(list)
        self._wildcard_handlers: list[EventHandler] = []
        self._history: list[SystemEvent] = []
        self._lock = threading.Lock()
        self._max_history: int = 1000

    def subscribe(
        self,
        event_type: EventType | None,
        handler: EventHandler,
    ) -> None:
        """Subscribe a handler to an event type.

        Args:
            event_type: Type to subscribe to, or None for all events.
            handler: Async callable receiving ``SystemEvent``.
        """
        with self._lock:
            if event_type is None:
                self._wildcard_handlers.append(handler)
            else:
                self._handlers[event_type].append(handler)

    def unsubscribe(
        self,
        event_type: EventType | None,
        handler: EventHandler,
    ) -> bool:
        """Remove a subscription.

        Args:
            event_type: The type to unsubscribe from.
            handler: The handler to remove.

        Returns:
            True if found and removed.
        """
        with self._lock:
            if event_type is None:
                try:
                    self._wildcard_handlers.remove(handler)
                    return True
                except ValueError:
                    return False
            try:
                self._handlers[event_type].remove(handler)
                return True
            except ValueError:
                return False

    async def emit(self, event: SystemEvent) -> None:
        """Emit an event to all subscribers.

        Args:
            event: The event to emit.
        """
        with self._lock:
            handlers = list(
                self._handlers.get(event.event_type, [])
            )
            wildcard = list(self._wildcard_handlers)
            self._history.append(event)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]

        for handler in handlers:
            try:
                await handler(event)
            except Exception as exc:
                logger.error(
                    "Event handler %r failed for %s: %s",
                    handler,
                    event.event_type.value,
                    exc,
                )

        for handler in wildcard:
            try:
                await handler(event)
            except Exception as exc:
                logger.error(
                    "Wildcard handler %r failed for %s: %s",
                    handler,
                    event.event_type.value,
                    exc,
                )

    def get_history(
        self,
        event_type: EventType | None = None,
        limit: int = 50,
    ) -> list[SystemEvent]:
        """Get recent events, optionally filtered by type.

        Args:
            event_type: Optional filter.
            limit: Max entries.

        Returns:
            List of ``SystemEvent``.
        """
        with self._lock:
            events = self._history
            if event_type:
                events = [e for e in events if e.event_type == event_type]
            return events[-limit:]

    def clear_history(self) -> None:
        with self._lock:
            self._history.clear()


# ── Error classifier ──────────────────────────────────────────────────


class ErrorClassifier:
    """Classify exceptions into ``ErrorCategory`` and ``ErrorSeverity``.

    Uses type-based rules with an extensible registration API.
    """

    def __init__(self) -> None:
        self._type_rules: dict[type, tuple[ErrorCategory, ErrorSeverity]] = {}

        # Built-in defaults
        self._register_defaults()

    def _register_defaults(self) -> None:
        import asyncio

        for exc_type in (
            TimeoutError,
            asyncio.TimeoutError,
            ConnectionError,
            ConnectionRefusedError,
            ConnectionResetError,
        ):
            self.register(exc_type, ErrorCategory.TEMPORARY, ErrorSeverity.LOW)

        for exc_type in (
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
        ):
            self.register(exc_type, ErrorCategory.PERMANENT, ErrorSeverity.MEDIUM)

        self.register(PermissionError, ErrorCategory.PERMANENT, ErrorSeverity.HIGH)
        self.register(RuntimeError, ErrorCategory.SYSTEM, ErrorSeverity.HIGH)
        self.register(MemoryError, ErrorCategory.SYSTEM, ErrorSeverity.CRITICAL)

    def register(
        self,
        exc_type: type[BaseException],
        category: ErrorCategory,
        severity: ErrorSeverity,
    ) -> None:
        """Register a classification rule for an exception type.

        Args:
            exc_type: The exception class.
            category: Its category.
            severity: Its severity.
        """
        self._type_rules[exc_type] = (category, severity)

    def classify(self, exc: BaseException) -> tuple[ErrorCategory, ErrorSeverity]:
        """Classify an exception.

        Args:
            exc: The exception to classify.

        Returns:
            ``(category, severity)`` tuple.
        """
        for exc_type in type(exc).__mro__:
            if exc_type in self._type_rules:
                return self._type_rules[exc_type]
        return (ErrorCategory.UNKNOWN, ErrorSeverity.MEDIUM)


# ── Centralized error handler ─────────────────────────────────────────


class ErrorResponse:
    """Structured error response.

    Attributes:
        error_id: Unique identifier for tracking.
        category: Classified category.
        severity: Classified severity.
        message: Human-readable message.
        original_exception: The original exception, if captured.
        timestamp: When the error occurred.
        resolved: Whether the error has been handled.
    """

    def __init__(
        self,
        error_id: str,
        category: ErrorCategory,
        severity: ErrorSeverity,
        message: str,
        original_exception: BaseException | None = None,
    ) -> None:
        self.error_id = error_id
        self.category = category
        self.severity = severity
        self.message = message
        self.original_exception = original_exception
        self.timestamp = time.time()
        self.resolved = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_id": self.error_id,
            "category": self.category.value,
            "severity": self.severity.value,
            "message": self.message,
            "timestamp": self.timestamp,
            "resolved": self.resolved,
        }


ErrorHandlerFn = Callable[[ErrorResponse], Awaitable[None]]


class CentralizedErrorHandler:
    """Centralized error handling with classification, callbacks, and event emission.

    Attributes:
        classifier: ``ErrorClassifier`` instance.
        event_bus: Optional ``EventBus`` for emitting error events.
    """

    def __init__(
        self,
        classifier: ErrorClassifier | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.classifier = classifier or ErrorClassifier()
        self.event_bus = event_bus
        self._handlers: list[ErrorHandlerFn] = []
        self._lock = threading.Lock()

    def add_handler(self, handler: ErrorHandlerFn) -> None:
        """Add an error handler callback.

        Args:
            handler: Async callable receiving ``ErrorResponse``.
        """
        with self._lock:
            self._handlers.append(handler)

    def remove_handler(self, handler: ErrorHandlerFn) -> bool:
        with self._lock:
            try:
                self._handlers.remove(handler)
                return True
            except ValueError:
                return False

    async def handle(
        self,
        exception: BaseException,
        context: dict[str, Any] | None = None,
    ) -> ErrorResponse:
        """Handle an exception: classify, run handlers, emit event.

        Args:
            exception: The exception to handle.
            context: Optional contextual metadata.

        Returns:
            An ``ErrorResponse``.
        """
        category, severity = self.classifier.classify(exception)
        error_id = str(uuid.uuid4())
        message = f"[{category.value}/{severity.value}] {exception}"

        response = ErrorResponse(
            error_id=error_id,
            category=category,
            severity=severity,
            message=message,
            original_exception=exception,
        )

        with self._lock:
            handlers = list(self._handlers)

        for handler in handlers:
            try:
                await handler(response)
            except Exception as exc:
                logger.error("Error handler %r failed: %s", handler, exc)

        if self.event_bus:
            await self.event_bus.emit(
                SystemEvent(
                    event_type=EventType.ERROR_OCCURRED,
                    source="CentralizedErrorHandler",
                    payload={
                        "error_id": error_id,
                        "category": category.value,
                        "severity": severity.value,
                        "message": str(exception),
                        "context": context,
                    },
                )
            )

        response.resolved = True
        return response

    def wrap(self, func: Callable[..., Any]) -> Callable[..., Any]:
        """Decorator that catches exceptions and routes them through handle().

        Args:
            func: The function to wrap.

        Returns:
            A wrapped function that returns the function's result or
            an ``ErrorResponse`` on failure.
        """
        import functools

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await func(*args, **kwargs) if asyncio.iscoroutinefunction(func) else func(*args, **kwargs)
            except Exception as exc:
                return await self.handle(exc)

        return wrapper


# ── Circuit breaker ───────────────────────────────────────────────────


class CircuitState(str, enum.Enum):
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing — rejects requests
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitBreaker:
    """Circuit breaker with configurable thresholds and recovery.

    States: CLOSED → OPEN (on failure threshold) → HALF_OPEN (after timeout)
    → CLOSED (on recovery) or OPEN (on failure).

    Attributes:
        name: Circuit identifier.
        failure_threshold: Failures before opening.
        recovery_timeout: Seconds before transitioning to half-open.
        consecutive_successes_to_close: Successes in half-open to close.
        state: Current state.
    """

    def __init__(
        self,
        name: str = "",
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        consecutive_successes_to_close: int = 3,
        event_bus: EventBus | None = None,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.consecutive_successes_to_close = consecutive_successes_to_close
        self.event_bus = event_bus

        self.state: CircuitState = CircuitState.CLOSED
        self._failure_count: int = 0
        self._consecutive_successes: int = 0
        self._last_failure_time: float = 0.0
        self._lock = threading.Lock()

    def record_success(self) -> None:
        with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                self._consecutive_successes += 1
                if (
                    self._consecutive_successes
                    >= self.consecutive_successes_to_close
                ):
                    self._set_state(CircuitState.CLOSED)
                    self._failure_count = 0
                    self._consecutive_successes = 0
            elif self.state == CircuitState.CLOSED:
                self._failure_count = 0

    def record_failure(self) -> None:
        with self._lock:
            self._last_failure_time = time.time()
            if self.state == CircuitState.CLOSED:
                self._failure_count += 1
                if self._failure_count >= self.failure_threshold:
                    self._set_state(CircuitState.OPEN)
            elif self.state == CircuitState.HALF_OPEN:
                self._set_state(CircuitState.OPEN)

    def allow_request(self) -> bool:
        """Check if a request is allowed through the circuit.

        Returns:
            True if the request should be allowed.
        """
        with self._lock:
            if self.state == CircuitState.CLOSED:
                return True
            if self.state == CircuitState.OPEN:
                if (time.time() - self._last_failure_time) >= self.recovery_timeout:
                    self._set_state(CircuitState.HALF_OPEN)
                    self._consecutive_successes = 0
                    return True
                return False
            # HALF_OPEN — allow one request
            return True

    def get_metrics(self) -> dict[str, Any]:
        with self._lock:
            return {
                "name": self.name,
                "state": self.state.value,
                "failure_count": self._failure_count,
                "consecutive_successes": self._consecutive_successes,
                "failure_threshold": self.failure_threshold,
                "recovery_timeout": self.recovery_timeout,
            }

    def reset(self) -> None:
        with self._lock:
            self._set_state(CircuitState.CLOSED)
            self._failure_count = 0
            self._consecutive_successes = 0

    def _set_state(self, new_state: CircuitState) -> None:
        old_state = self.state
        self.state = new_state
        if old_state != new_state and self.event_bus:
            event_type_map = {
                CircuitState.OPEN: EventType.CIRCUIT_OPEN,
                CircuitState.HALF_OPEN: EventType.CIRCUIT_HALF_OPEN,
                CircuitState.CLOSED: EventType.CIRCUIT_CLOSED,
            }
            mapped = event_type_map.get(new_state)
            if mapped:
                import asyncio

                asyncio.ensure_future(
                    self.event_bus.emit(
                        SystemEvent(
                            event_type=mapped,
                            source=f"CircuitBreaker:{self.name}",
                            payload={
                                "old_state": old_state.value,
                                "new_state": new_state.value,
                            },
                        )
                    )
                )


# ── Retry handler ─────────────────────────────────────────────────────


class RetryHandler:
    """Configurable retry with exponential backoff.

    Attributes:
        max_retries: Maximum retry attempts.
        base_delay: Initial delay in seconds.
        max_delay: Maximum delay in seconds.
        backoff_factor: Exponential backoff multiplier.
    """

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        backoff_factor: float = 2.0,
    ) -> None:
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor

    async def execute(
        self,
        func: Callable[..., Awaitable[Any]],
        *args: Any,
        retryable_exceptions: tuple[type, ...] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Execute a function with retry logic.

        Args:
            func: The async function to execute.
            *args: Positional arguments for the function.
            retryable_exceptions: Exception types to retry on.
            **kwargs: Keyword arguments for the function.

        Returns:
            The function's return value.

        Raises:
            The last exception if all retries are exhausted.
        """
        if retryable_exceptions is None:
            retryable_exceptions = (
                TimeoutError,
                ConnectionError,
                ConnectionRefusedError,
                ConnectionResetError,
            )

        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return await func(*args, **kwargs)
            except retryable_exceptions as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    delay = min(
                        self.base_delay * (self.backoff_factor ** attempt),
                        self.max_delay,
                    )
                    logger.info(
                        "Retry %d/%d for %s after %.2fs: %s",
                        attempt + 1,
                        self.max_retries,
                        func.__qualname__,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "All %d retries exhausted for %s: %s",
                        self.max_retries,
                        func.__qualname__,
                        exc,
                    )
            except Exception as exc:
                # Non-retryable — raise immediately
                raise exc

        if last_exc:
            raise last_exc  # pragma: no cover


# ── Kafka/ActiveMQ integration stubs ──────────────────────────────────


class MessageQueueEventProducer:
    """Stub for integration with Kafka/ActiveMQ.

    Provides an interface to produce events to external message queues.
    Actual integration requires an external message queue client library.
    """

    def __init__(
        self,
        event_bus: EventBus,
        topic_prefix: str = "vertex",
    ) -> None:
        self.event_bus = event_bus
        self.topic_prefix = topic_prefix
        self._running = False
        self._produced: list[SystemEvent] = []

    def get_produced_events(self) -> list[SystemEvent]:
        return list(self._produced)

    async def start(self) -> None:
        """Start forwarding events from the event bus to the message queue."""
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def _on_event(self, event: SystemEvent) -> None:
        if not self._running:
            return
        topic = f"{self.topic_prefix}.{event.event_type.value.replace('.', '_')}"
        self._produced.append(event)
        # In production, produce to Kafka/ActiveMQ here:
        # await producer.send(topic, event.to_dict())
        logger.debug("Produced event to %s: %s", topic, event.event_type.value)


def _ensure_supported() -> bool:
    """Check if kafka-python or stomp.py is available."""
    try:
        __import__("kafka")
        return True
    except ImportError:
        pass
    try:
        __import__("stomp")
        return True
    except ImportError:
        pass
    return False


__all__ = [
    "CentralizedErrorHandler",
    "CircuitBreaker",
    "CircuitState",
    "ErrorCategory",
    "ErrorClassifier",
    "ErrorResponse",
    "ErrorSeverity",
    "EventBus",
    "EventHandler",
    "EventType",
    "MessageQueueEventProducer",
    "RetryHandler",
    "SystemEvent",
]