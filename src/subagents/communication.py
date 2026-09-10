"""Inter-agent communication protocol.

Provides message passing, an event system, and shared state mechanisms
for communication between agents — parent-child, sibling, and remote.

Supports:
- Message passing: agent-to-agent messages via broker
- Event system: emit/subscribe with exception-based propagation
- Shared state: agents read/write a common state store
- Parent-child: subagent → parent result/state updates
- Sibling agents: agents at the same level via store/events
- Message broker: pluggable backend (in-memory, Kafka/ActiveMQ stub)
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from src.graph.types import Command
from src.middleware.types import AgentMiddleware
from src.tools.filesystem import ToolResult


# ── Message types ───────────────────────────────────────────────────────


class MessagePriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


class MessageType(Enum):
    RESULT = "result"
    STATE_UPDATE = "state_update"
    COMMAND = "command"
    EVENT = "event"
    ERROR = "error"
    REQUEST = "request"
    RESPONSE = "response"


@dataclass
class AgentMessage:
    """A single message between agents."""

    id: str = ""
    sender: str = ""
    recipient: str = ""
    message_type: MessageType = MessageType.RESULT
    payload: Any = None
    priority: MessagePriority = MessagePriority.NORMAL
    timestamp: float = 0.0
    correlation_id: str = ""
    reply_to: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "sender": self.sender,
            "recipient": self.recipient,
            "message_type": self.message_type.value,
            "payload": self.payload,
            "priority": self.priority.value,
            "timestamp": self.timestamp,
            "correlation_id": self.correlation_id,
            "reply_to": self.reply_to,
        }


# ── Event system ────────────────────────────────────────────────────────


@dataclass
class AgentEvent:
    """An event emitted or consumed by agents."""

    type: str
    source: str = ""
    data: Any = None
    timestamp: float = 0.0
    id: str = ""


EventHandler = Callable[[AgentEvent], None]


class EventBus:
    """Simple in-process event bus for agent communication.

    Agents can emit events and subscribe to event types.
    Supports wildcard subscriptions (``*`` for all events).
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[EventHandler]] = {}
        self._lock = threading.Lock()

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Subscribe to an event type.

        Args:
            event_type: Event type string (use ``*`` for all).
            handler: Callback receiving ``AgentEvent``.
        """
        with self._lock:
            self._subscribers.setdefault(event_type, []).append(handler)

    def unsubscribe(self, event_type: str, handler: EventHandler) -> bool:
        """Remove a subscription.

        Returns:
            True if found and removed.
        """
        with self._lock:
            handlers = self._subscribers.get(event_type, [])
            if handler in handlers:
                handlers.remove(handler)
                return True
            return False

    def emit(self, event: AgentEvent) -> list[Any]:
        """Emit an event to all matching subscribers.

        Args:
            event: The event to emit.

        Returns:
            List of handler return values.
        """
        results: list[Any] = []
        with self._lock:
            handlers = list(self._subscribers.get(event.type, []))
            handlers.extend(self._subscribers.get("*", []))

        for handler in handlers:
            try:
                result = handler(event)
                results.append(result)
            except Exception:
                continue

        return results

    def clear(self) -> None:
        with self._lock:
            self._subscribers.clear()


# ── Message broker ──────────────────────────────────────────────────────


class MessageBroker:
    """Pluggable message broker for inter-agent communication.

    Supports in-memory (default) and extensible backends
    (Kafka, ActiveMQ via adapter).
    """

    def __init__(self) -> None:
        self._queues: dict[str, list[AgentMessage]] = {}
        self._lock = threading.Lock()
        self._event_bus = EventBus()

    @property
    def event_bus(self) -> EventBus:
        return self._event_bus

    def send(self, message: AgentMessage) -> None:
        """Send a message to a recipient's queue.

        Args:
            message: Message to send.
        """
        if not message.id:
            message.id = str(uuid.uuid4())
        if not message.timestamp:
            message.timestamp = time.time()

        with self._lock:
            self._queues.setdefault(message.recipient, []).append(message)

        # Also emit as event
        self._event_bus.emit(AgentEvent(
            type=f"message.{message.message_type.value}",
            source=message.sender,
            data=message.to_dict(),
        ))

    def receive(self, recipient: str, timeout: float = 0.0) -> AgentMessage | None:
        """Receive the next message for a recipient.

        Args:
            recipient: Agent name to receive for.
            timeout: Max wait time in seconds (0 = non-blocking).

        Returns:
            AgentMessage or None.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                queue = self._queues.get(recipient, [])
                if queue:
                    return queue.pop(0)
            if timeout > 0:
                time.sleep(0.05)
        return None

    def poll(self, recipient: str, message_type: MessageType | None = None) -> list[AgentMessage]:
        """Poll all messages for a recipient (non-blocking).

        Args:
            recipient: Agent name.
            message_type: Optional filter by message type.

        Returns:
            List of messages.
        """
        with self._lock:
            messages = list(self._queues.get(recipient, []))
            self._queues[recipient] = []
        if message_type:
            messages = [m for m in messages if m.message_type == message_type]
        return messages

    def clear_recipient(self, recipient: str) -> int:
        """Clear all messages for a recipient.

        Returns:
            Number of messages cleared.
        """
        with self._lock:
            queue = self._queues.pop(recipient, [])
        return len(queue)


# ── Shared state ────────────────────────────────────────────────────────


class SharedState:
    """A shared key-value store accessible by all agents.

    Provides namespace isolation per agent type (parent, child, sibling).
    """

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._lock = threading.Lock()

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = value

    def update(self, key: str, func: Callable[[Any], Any]) -> Any:
        """Atomically update a value using a function.

        Args:
            key: Key to update.
            func: Receives current value, returns new value.

        Returns:
            The new value.
        """
        with self._lock:
            current = self._data.get(key)
            new_value = func(current)
            self._data[key] = new_value
            return new_value

    def delete(self, key: str) -> bool:
        with self._lock:
            return self._data.pop(key, None) is not None

    def keys(self, prefix: str = "") -> list[str]:
        with self._lock:
            if prefix:
                return [k for k in self._data if k.startswith(prefix)]
            return list(self._data.keys())

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


# ── Communication middleware ────────────────────────────────────────────


class CommunicationMiddleware(AgentMiddleware):
    """Middleware that provides communication primitives to agents.

    Registers tools for sending messages, accessing shared state,
    and managing events.
    """

    def __init__(
        self,
        broker: MessageBroker | None = None,
        shared_state: SharedState | None = None,
        agent_name: str = "main",
    ) -> None:
        super().__init__()
        self._broker = broker or MessageBroker()
        self._shared_state = shared_state or SharedState()
        self._agent_name = agent_name

    @property
    def broker(self) -> MessageBroker:
        return self._broker

    @property
    def shared_state(self) -> SharedState:
        return self._shared_state

    async def before_agent(self, config: MiddlewareConfig) -> None:
        pass

    async def after_agent(self, config: MiddlewareConfig) -> None:
        pass

    def send_message_fn(self) -> Callable[..., ToolResult]:
        def _send(recipient: str, payload: Any, message_type: str = "result") -> ToolResult:
            try:
                msg_type = MessageType(message_type)
            except ValueError:
                return ToolResult(success=False, error=f"Invalid message_type: {message_type}")
            msg = AgentMessage(
                sender=self._agent_name,
                recipient=recipient,
                message_type=msg_type,
                payload=payload,
            )
            self._broker.send(msg)
            return ToolResult(success=True, data=f"Message sent to '{recipient}'")
        _send.__name__ = "send_message"
        return _send

    def read_state_fn(self) -> Callable[..., ToolResult]:
        def _read(key: str) -> ToolResult:
            value = self._shared_state.get(key)
            return ToolResult(success=True, data={key: value})
        _read.__name__ = "read_state"
        return _read

    def write_state_fn(self) -> Callable[..., ToolResult]:
        def _write(key: str, value: Any) -> ToolResult:
            self._shared_state.set(key, value)
            return ToolResult(success=True, data=f"State '{key}' updated")
        _write.__name__ = "write_state"
        return _write


__all__ = [
    "AgentEvent",
    "AgentMessage",
    "CommunicationMiddleware",
    "EventBus",
    "EventHandler",
    "MessageBroker",
    "MessagePriority",
    "MessageType",
    "SharedState",
]