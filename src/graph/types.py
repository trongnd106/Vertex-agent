"""Core graph types for the agent graph system.

Defines the foundational types, protocols, and data structures used across
all graph components. Inspired by LangGraph's type system
(``langgraph/types.py``, ``langgraph/pregel/protocol.py``) and adapted for
the agent orchestration use-case.

Hierarchy::

    AgentState (base state schema)
        → AgentNode (node definition)
            → CompiledGraph (runtime executable)
    Channel/Reducer (state management)
    PregelLoop (execution engine)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Generic, Literal, Protocol, TypeVar, Union

# ──────────────────────────────────────────────────────────────────────
# Type variables
# ──────────────────────────────────────────────────────────────────────

T = TypeVar("T")
"""Generic type for channel values."""
U = TypeVar("U")
"""Generic type for channel updates."""
StateT = TypeVar("StateT", bound=dict[str, Any])
"""Generic bound for agent state types."""
NodeT = TypeVar("NodeT")
"""Generic bound for node output types."""
InT = TypeVar("InT", contravariant=True)
"""Input type for Runnable protocol."""
OutT = TypeVar("OutT", covariant=True)
"""Output type for Runnable protocol."""

# ──────────────────────────────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────────────────────────────


class StreamMode(str, Enum):
    """Stream output modes."""

    VALUES = "values"
    """Emit full state values at each step."""
    UPDATES = "updates"
    """Emit only changed values."""
    MESSAGES = "messages"
    """Emit message chunks as they arrive."""
    EVENTS = "events"
    """Emit structured events (tool calls, errors, progress)."""
    DEBUG = "debug"
    """Emit full debug information including internal state."""


class InterruptAction(Enum):
    """Actions the agent can take when interrupted."""

    CONTINUE = auto()
    """Resume normal execution."""
    RETRY = auto()
    """Retry the last step."""
    STOP = auto()
    """Stop execution entirely."""
    SKIP = auto()
    """Skip the current step and continue."""


# ──────────────────────────────────────────────────────────────────────
# Core data types
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Send(Generic[StateT]):
    """Dynamic message to a node, enabling map-reduce fan-out.

    Analogous to LangGraph's ``langgraph.types.Send``: when a node returns
    one or more ``Send`` objects, the runtime schedules the named node with
    the given state for the next parallel step.
    """

    node: str
    """Target node name."""
    state: StateT
    """State to pass to the target node."""


@dataclass(frozen=True)
class Command(Generic[StateT]):
    """Graph control primitive: update state, goto node, or resume.

    Analogous to LangGraph's ``langgraph.types.Command``. A node may return
    a ``Command`` to:
    - ``goto``: jump to another node (overriding default edges).
    - ``update``: directly update state fields.
    - ``resume``: provide a value to resume from an interrupt.
    """

    goto: str | Send[StateT] | None = None
    """Target node or Send for dynamic routing."""
    update: dict[str, Any] | None = None
    """State updates to apply before the next step."""
    resume: Any | None = None
    """Value to resume from an interrupt (human-in-the-loop)."""


@dataclass(frozen=True)
class Interrupt:
    """Information about an interrupt point.

    When a node calls ``interrupt(value)``, the runtime saves a checkpoint
    and returns control with this object describing the interrupt.
    """

    value: Any
    """The value passed to ``interrupt()``."""
    node: str
    """The node that raised the interrupt."""
    step: int
    """The step number at which the interrupt occurred."""
    resume: Any = None
    """Optional resume value if already provided."""


@dataclass(frozen=True)
class RetryPolicy:
    """Retry policy for node execution.

    Same semantics as LangGraph's ``RetryPolicy``.
    """

    max_attempts: int = 3
    """Maximum number of execution attempts."""
    initial_interval: float = 0.5
    """Initial retry interval in seconds."""
    max_interval: float = 60.0
    """Maximum retry interval in seconds."""
    backoff_factor: float = 2.0
    """Multiplier for exponential backoff."""
    jitter: bool = True
    """Whether to add random jitter to intervals."""
    retry_on: tuple[type[Exception], ...] = (Exception,)
    """Exception types that trigger a retry."""
    retry_on_timeout: bool = True
    """Whether to retry on timeout errors."""


@dataclass(frozen=True)
class TimeoutPolicy:
    """Timeout policy for node execution."""

    seconds: float = 60.0
    """Maximum execution time in seconds."""
    graceful: bool = True
    """Whether to attempt graceful cancellation before hard kill."""


@dataclass(frozen=True)
class CachePolicy:
    """Cache policy for node output."""

    enabled: bool = False
    """Whether caching is enabled."""
    ttl_seconds: float | None = 300.0
    """Time-to-live in seconds. ``None`` = no expiry."""
    max_size: int = 256
    """Maximum number of cached entries."""


# ──────────────────────────────────────────────────────────────────────
# Protocols / ABCs
# ──────────────────────────────────────────────────────────────────────


class Runnable(Protocol[InT, OutT]):
    """Protocol for invocable components.

    Mirrors ``langchain_core.runnables.Runnable`` but without forcing
    the dependency. Components that implement this protocol can be
    used in graph nodes.
    """

    def invoke(self, input: InT, **kwargs: Any) -> OutT:
        """Synchronously invoke the component."""
        ...

    async def ainvoke(self, input: InT, **kwargs: Any) -> OutT:
        """Asynchronously invoke the component."""
        ...

    def stream(
        self, input: InT, **kwargs: Any
    ) -> Iterator[OutT]:
        """Synchronously stream output."""
        ...

    def astream(
        self, input: InT, **kwargs: Any
    ) -> AsyncIterator[OutT]:
        """Asynchronously stream output."""
        ...


class NodeProtocol(Protocol[StateT]):
    """Protocol for graph node functions.

    A node function receives the current state and returns either a
    state update dict, a Command, a Send, or a list of Sends.
    """

    def __call__(
        self,
        state: StateT,
        **kwargs: Any,
    ) -> dict[str, Any] | Command[Any] | Send[Any] | list[Send[Any]]:
        ...


# ──────────────────────────────────────────────────────────────────────
# Channel types
# ──────────────────────────────────────────────────────────────────────


class BaseChannel(ABC, Generic[T, U]):
    """Abstract base channel for state field management.

    Each channel wraps a single state field and controls how updates
    are applied (overwrite, accumulate, reduce, etc.). Inspired by
    LangGraph's ``BaseChannel`` (``langgraph/channels/base.py``).
    """

    @property
    @abstractmethod
    def value(self) -> T:
        """Current channel value."""
        ...

    @abstractmethod
    def update(self, values: Sequence[U]) -> bool:
        """Apply a batch of updates to this channel.

        Args:
            values: The new values to apply.

        Returns:
            True if the value changed, False otherwise.
        """
        ...

    @abstractmethod
    def checkpoint(self) -> T:
        """Return a serializable snapshot of the current value."""
        ...

    @abstractmethod
    def from_checkpoint(self, checkpoint: T) -> None:
        """Restore value from a checkpoint snapshot."""
        ...

    @abstractmethod
    def reset(self) -> None:
        """Reset channel to its initial state."""
        ...


# ──────────────────────────────────────────────────────────────────────
# Execution types
# ──────────────────────────────────────────────────────────────────────


@dataclass
class StreamChunk:
    """A single chunk of streamed output.

    Mirrors the StreamChunk from ``src/streaming/chunks.py`` in the
    orchestrator streaming pipeline.
    """

    content: str | None = None
    """Text content delta."""
    reasoning: str | None = None
    """Reasoning/thinking delta."""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    """Tool call fragments."""
    tool_result: Any = None
    """Tool execution result."""
    finish_reason: str | None = None
    """Reason for finishing: 'stop' | 'length' | 'tool_calls' | 'cancelled'."""
    node_name: str = ""
    """Name of the node that produced this chunk."""
    step: int = 0
    """Step number in the execution."""
    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional metadata."""


@dataclass
class ExecutionResult:
    """Result of a graph execution."""

    state: dict[str, Any]
    """Final graph state."""
    steps: int = 0
    """Number of steps executed."""
    total_duration: float = 0.0
    """Total execution time in seconds."""
    interrupted: Interrupt | None = None
    """Interrupt information if execution was interrupted."""
    error: Exception | None = None
    """Error if execution failed."""


# Sentinel constants for graph start/end
START = "__start__"
"""Virtual node: graph execution starts here."""
END = "__end__"
"""Virtual node: graph execution terminates here."""


class EdgeDefinition:
    """Definition of a directed edge between two nodes."""

    def __init__(self, source: str, target: str) -> None:
        self.source = source
        self.target = target


class ConditionalEdgeDefinition:
    """Definition of a conditional edge with a router function."""

    def __init__(
        self,
        source: str,
        router: Callable[[dict[str, Any]], str],
        path_map: dict[str, str],
    ) -> None:
        self.source = source
        self.router = router
        self.path_map = dict(path_map)


__all__ = [
    "BaseChannel",
    "CachePolicy",
    "Command",
    "ConditionalEdgeDefinition",
    "EdgeDefinition",
    "END",
    "ExecutionResult",
    "Interrupt",
    "InterruptAction",
    "NodeProtocol",
    "RetryPolicy",
    "Runnable",
    "Send",
    "START",
    "StreamChunk",
    "StreamMode",
    "TimeoutPolicy",
]