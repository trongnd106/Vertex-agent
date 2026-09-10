"""Core types for the middleware pipeline.

Defines the base ``AgentMiddleware`` abstract class with lifecycle hooks,
``MiddlewareConfig`` for runtime configuration, and supporting types.
Inspired by DeepAgents' ``middleware/__init__.py``, LangChain's
``AgentMiddleware`` abstraction, and orchestrator's middleware stack.

Middleware ordering follows the Chain-of-Responsibility pattern::

    before_agent  (top→bottom, outer→inner)
        ↓
    wrap_model_call  (intercept chain)
        ↓
    before_model  (pre-inference)
        ↓
    LLM inference
        ↑
    modify_response  (post-inference)
        ↑
    wrap_model_call  (unwind)
        ↑
    after_agent  (bottom→top, inner→outer)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Generic, Protocol, TypeVar

# ──────────────────────────────────────────────────────────────────────
# Type variables
# ──────────────────────────────────────────────────────────────────────

StateT = TypeVar("StateT", bound=dict[str, Any])
"""Generic bound for agent state."""
RequestT = TypeVar("RequestT", contravariant=True)
"""Generic for model request types."""
ResponseT = TypeVar("ResponseT", covariant=True)
"""Generic for model response types."""

# ──────────────────────────────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────────────────────────────


class MiddlewarePosition(Enum):
    """Where a middleware sits in the stack."""

    BASE = auto()
    """Core middleware (prepended automatically)."""
    CALLER = auto()
    """User-provided middleware (added by caller)."""
    TAIL = auto()
    """Tail middleware (appended at the end)."""


class TriggerMode(Enum):
    """Trigger modes for summarization middleware."""

    FRACTION = "fraction"
    """Trigger based on fraction of context window used."""
    ABSOLUTE = "absolute"
    """Trigger based on absolute token count."""
    MESSAGES = "messages"
    """Trigger based on number of messages."""


# ──────────────────────────────────────────────────────────────────────
# Data types
# ──────────────────────────────────────────────────────────────────────


@dataclass
class ModelRequest:
    """A request to the LLM model.

    This is what flows through the middleware chain.  Each middleware
    can inspect and modify the request before it reaches the model.
    """

    messages: list[dict[str, Any]]
    """The message list sent to the model."""
    system_prompt: str | None = None
    """Optional system prompt override."""
    tools: list[Any] = field(default_factory=list)
    """Tools available to the model."""
    extra_body: dict[str, Any] = field(default_factory=dict)
    """Extra body parameters for the model API."""
    model_name: str | None = None
    """Model identifier override."""


@dataclass
class MiddlewareConfig:
    """Runtime configuration passed to middleware hooks.

    Provides access to the runtime context — state, store, checkpointer,
    streaming, and other cross-cutting concerns.
    """

    thread_id: str = ""
    """Conversation/session thread ID."""
    user_id: str = ""
    """User identifier."""
    configurable: dict[str, Any] = field(default_factory=dict)
    """Arbitrary configurable parameters."""
    store: Any = None
    """Long-term memory store."""
    checkpointer: Any = None
    """Checkpointer for state persistence."""
    stream_callback: Callable[[Any], None] | None = None
    """Callback for streaming chunks."""
    debug: bool = False
    """Enable debug output."""
    tags: list[str] = field(default_factory=list)
    """Tags for observability/tracing."""


@dataclass
class MiddlewareResult:
    """Result of a middleware hook execution.

    Middleware can return an updated result to modify state or signal
    that execution should be halted.
    """

    state: dict[str, Any] | None = None
    """Updated state (or None if unchanged)."""
    output: Any = None
    """Output to return (signals halt if set)."""
    halt: bool = False
    """If True, stop middleware chain execution."""
    feedback: str = ""
    """Feedback message (e.g. rubric evaluation feedback)."""


# ──────────────────────────────────────────────────────────────────────
# Protocol: model call handler
# ──────────────────────────────────────────────────────────────────────


class ModelCallHandler(Protocol[RequestT, ResponseT]):
    """Protocol for the next handler in the model-call chain.

    Each middleware either passes the request to the next handler
    (``handler(request)``) or short-circuits by returning directly.
    """

    def __call__(self, request: RequestT) -> ResponseT:
        """Invoke the next handler in the chain."""
        ...


class AsyncModelCallHandler(Protocol[RequestT, ResponseT]):
    """Async protocol for the next handler in the model-call chain."""

    async def __call__(self, request: RequestT) -> ResponseT:
        """Invoke the next handler asynchronously."""
        ...


# ──────────────────────────────────────────────────────────────────────
# AgentMiddleware base class
# ──────────────────────────────────────────────────────────────────────


class AgentMiddleware(ABC, Generic[StateT]):
    """Abstract base class for all middleware components.

    Middleware follows the Chain-of-Responsibility pattern:

    1. ``before_agent`` — run before the agent executes (top→bottom)
    2. ``wrap_model_call`` / ``awrap_model_call`` — intercept the model request chain
    3. ``before_model`` — run just before model inference
    4. ``after_agent`` — run after agent completes (bottom→top, reversed)

    Subclasses override the hooks they need.  All hooks have default
    no-op implementations so subclasses only override what they need.
    """

    # ── Identity ──────────────────────────────────────────────────────

    name: str = "base_middleware"
    """Unique identifier for this middleware."""
    state_schema: type[StateT] | None = None
    """Optional state fields this middleware contributes."""
    tools: list[Any] | None = None
    """Tools contributed by this middleware."""
    trace_policy: Any = None
    """Trace policy for observability (deepagents compatibility)."""
    wrap_tool_call: Any = None
    """Intercept tool execution for retries, monitoring, or modification."""
    awrap_tool_call: Any = None
    """Async version of wrap_tool_call."""
    system_prompt: str | None = None
    """System prompt injection from this middleware."""
    order: int = 0
    """Ordering weight (lower = runs first)."""

    # ── Lifecycle hooks ───────────────────────────────────────────────

    def before_agent(
        self,
        state: dict[str, Any],
        runtime: Any,
        config: MiddlewareConfig,
    ) -> MiddlewareResult | None:
        """Hook called before the agent executes.

        Middleware can inspect/modify state, inject tools, or halt
        execution by returning a ``MiddlewareResult`` with ``halt=True``.

        Args:
            state: Current agent state.
            runtime: Runtime context (graph, store, etc.).
            config: Runtime configuration.

        Returns:
            ``MiddlewareResult`` to apply state changes or halt, or None.
        """
        return None

    def after_agent(
        self,
        state: dict[str, Any],
        runtime: Any,
        config: MiddlewareConfig,
    ) -> MiddlewareResult | None:
        """Hook called after the agent completes.

        Args:
            state: Final agent state.
            runtime: Runtime context.
            config: Runtime configuration.

        Returns:
            ``MiddlewareResult`` or None.
        """
        return None

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: ModelCallHandler[ModelRequest, Any],
    ) -> Any:
        """Synchronously intercept a model call.

        Middleware can inspect/modify the request before passing it to the
        next handler, and/or modify the response.

        Args:
            request: The model request.
            handler: The next handler in the chain.

        Returns:
            The response (from the next handler or short-circuited).
        """
        return handler(request)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: AsyncModelCallHandler[ModelRequest, Any],
    ) -> Any:
        """Asynchronously intercept a model call.

        Args:
            request: The model request.
            handler: The next async handler in the chain.

        Returns:
            The response.
        """
        return await handler(request)

    def modify_request(self, request: ModelRequest) -> ModelRequest:
        """Modify the model request before it's sent to the model.

        This is a simpler hook than ``wrap_model_call`` — it only allows
        modifying the request, not intercepting the chain.

        Args:
            request: The model request to modify.

        Returns:
            The (possibly modified) request.
        """
        return request

    def before_model(
        self,
        model: Any,
        config: MiddlewareConfig,
    ) -> None:
        """Hook called before model inference, after all modifications.

        Args:
            model: The model instance about to be called.
            config: Runtime configuration.
        """
        pass


__all__ = [
    "AgentMiddleware",
    "AsyncModelCallHandler",
    "MiddlewareConfig",
    "MiddlewarePosition",
    "MiddlewareResult",
    "ModelCallHandler",
    "ModelRequest",
    "TriggerMode",
]