"""Error handling and retry mechanisms for the agent graph.

Provides retry policies, error classification, and error handler
registration.  Inspired by LangGraph's ``RetryPolicy``
(``langgraph/types.py``) and ``pregel/_retry.py``.

Usage::

    @with_retry(max_attempts=3)
    def my_node(state):
        return process(state["messages"])
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import Any, TypeVar

from src.graph.types import RetryPolicy

StateT = TypeVar("StateT", bound=dict[str, Any])

# Type for an error handler function
ErrorHandler = Callable[[dict[str, Any], Exception], dict[str, Any] | None]

# Registry of error handlers
_error_handlers: dict[str, list[ErrorHandler]] = {}


# ── Error classification ─────────────────────────────────────────────


class GraphError(Exception):
    """Base exception for graph execution errors."""

    def __init__(
        self,
        message: str,
        *,
        node: str | None = None,
        step: int | None = None,
        recoverable: bool = True,
    ) -> None:
        super().__init__(message)
        self.node = node
        self.step = step
        self.recoverable = recoverable


class NodeExecutionError(GraphError):
    """Raised when a node function fails during execution."""


class ChannelError(GraphError):
    """Raised when a channel operation fails."""


class CompilationError(GraphError):
    """Raised during graph compilation (validation, channel setup)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, recoverable=False)


class TimeoutError(GraphError):
    """Raised when a node execution times out."""


class MaxRetriesExceeded(GraphError):
    """Raised when the maximum number of retry attempts has been exhausted."""

    def __init__(
        self,
        message: str,
        *,
        node: str | None = None,
        attempts: int = 0,
    ) -> None:
        super().__init__(message, node=node, step=None, recoverable=False)
        self.attempts = attempts


# ── Retry logic ──────────────────────────────────────────────────────


def compute_backoff(policy: RetryPolicy, attempt: int) -> float:
    """Compute the backoff delay for a given retry attempt.

    Args:
        policy: The retry policy.
        attempt: The attempt number (0-indexed).

    Returns:
        Delay in seconds before the next retry.
    """
    delay = policy.initial_interval * (policy.backoff_factor ** attempt)
    delay = min(delay, policy.max_interval)
    if policy.jitter:
        delay *= 0.5 + random.random() * 0.5
    return delay


def should_retry(policy: RetryPolicy, exception: Exception) -> bool:
    """Determine whether the exception should trigger a retry.

    Args:
        policy: The retry policy.
        exception: The exception raised.

    Returns:
        True if the exception type matches ``retry_on``.
    """
    for exc_type in policy.retry_on:
        if isinstance(exception, exc_type):
            return True
    return False


def with_retry(
    fn: Callable[..., Any] | None = None,
    *,
    max_attempts: int = 3,
    initial_interval: float = 0.5,
    max_interval: float = 60.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    retry_on: tuple[type[Exception], ...] = (Exception,),
) -> Callable[..., Any]:
    """Decorator that wraps a node function with retry logic.

    Can be used bare or with arguments::

        @with_retry
        def my_node(state): ...

        @with_retry(max_attempts=5, backoff_factor=3.0)
        def my_other_node(state): ...

    Args:
        fn: The function to wrap.
        max_attempts: Maximum number of attempts.
        initial_interval: Initial backoff interval.
        max_interval: Maximum backoff interval.
        backoff_factor: Backoff multiplier.
        jitter: Whether to add random jitter.
        retry_on: Exception types that trigger a retry.

    Returns:
        Wrapped function with retry behaviour.
    """
    policy = RetryPolicy(
        max_attempts=max_attempts,
        initial_interval=initial_interval,
        max_interval=max_interval,
        backoff_factor=backoff_factor,
        jitter=jitter,
        retry_on=retry_on,
    )

    def _decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        def _wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Exception | None = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except tuple(policy.retry_on) as exc:
                    last_exc = exc
                    if attempt < max_attempts - 1:
                        delay = compute_backoff(policy, attempt)
                        time.sleep(delay)
                    else:
                        raise MaxRetriesExceeded(
                            f"Function {func.__name__!r} failed after {max_attempts} attempts",
                            attempts=max_attempts,
                        ) from exc
            if last_exc:
                raise last_exc
            return None

        return _wrapper

    if fn is not None:
        return _decorator(fn)
    return _decorator


# ── Error handler registry ───────────────────────────────────────────


def register_error_handler(
    node_name: str,
    handler: ErrorHandler,
) -> None:
    """Register an error handler for a specific node.

    Args:
        node_name: Name of the node to handle errors for.
        handler: Callback ``(state, exception) -> state_update | None``.
    """
    _error_handlers.setdefault(node_name, []).append(handler)


def unregister_error_handler(node_name: str, handler: ErrorHandler) -> None:
    """Remove a previously registered error handler."""
    handlers = _error_handlers.get(node_name, [])
    if handler in handlers:
        handlers.remove(handler)


def clear_error_handlers() -> None:
    """Clear all registered error handlers."""
    _error_handlers.clear()


def get_error_handlers(node_name: str) -> list[ErrorHandler]:
    """Get all registered error handlers for a node."""
    return list(_error_handlers.get(node_name, []))


def run_error_handlers(
    node_name: str,
    state: dict[str, Any],
    exception: Exception,
) -> dict[str, Any] | None:
    """Execute all registered error handlers for a node.

    Handlers are called in registration order. If any returns a state
    update dict, that update is applied.

    Args:
        node_name: The node that failed.
        state: The current graph state.
        exception: The exception that was raised.

    Returns:
        Accumulated state updates, or ``None``.
    """
    result: dict[str, Any] = {}
    for handler in _error_handlers.get(node_name, []):
        try:
            update = handler(state, exception)
            if update:
                result.update(update)
        except Exception:
            pass
    return result or None


# ── Node-level retry wrapper ─────────────────────────────────────────


class RetryableNode:
    """Wraps a node function with retry and error handling.

    Combines the retry decorator with the error handler registry for
    comprehensive error management.
    """

    def __init__(
        self,
        fn: Callable[..., Any],
        *,
        policy: RetryPolicy | None = None,
        node_name: str | None = None,
    ) -> None:
        self._fn = fn
        self._policy = policy or RetryPolicy()
        self._node_name = node_name or getattr(fn, "__name__", "unknown")

    def execute(self, state: dict[str, Any]) -> Any:
        """Execute the node with retry and error handling."""
        last_exc: Exception | None = None

        for attempt in range(self._policy.max_attempts):
            try:
                return self._fn(state)
            except Exception as exc:
                last_exc = exc
                # Run error handlers
                run_error_handlers(self._node_name, state, exc)
                # Check if we should retry
                if attempt < self._policy.max_attempts - 1 and should_retry(
                    self._policy, exc
                ):
                    delay = compute_backoff(self._policy, attempt)
                    time.sleep(delay)
                else:
                    raise

        if last_exc:
            raise last_exc
        return None


__all__ = [
    "ChannelError",
    "CompilationError",
    "GraphError",
    "MaxRetriesExceeded",
    "NodeExecutionError",
    "RetryPolicy",
    "RetryableNode",
    "TimeoutError",
    "clear_error_handlers",
    "compute_backoff",
    "get_error_handlers",
    "register_error_handler",
    "run_error_handlers",
    "should_retry",
    "unregister_error_handler",
    "with_retry",
]