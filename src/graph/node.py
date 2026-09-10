"""Node definition system for the agent graph.

Defines how graph nodes are specified — either as plain callables or as
``AgentNode`` instances with lifecycle hooks (``before_node``, ``execute``,
``after_node``) and configurable error handling.

Inspired by LangGraph's ``PregelNode`` (``langgraph/pregel/_read.py``)
and the ``StateNodeSpec`` (``langgraph/graph/_node.py``).

Usage::

    @node
    def my_node(state: dict) -> dict:
        return {"result": process(state["messages"])}

    # or with lifecycle hooks:
    agent_node = AgentNode("processor")
    agent_node.before_node = lambda ctx: log("starting")
    agent_node.execute = my_logic
    agent_node.after_node = lambda ctx, result: log("done")
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

StateT = TypeVar("StateT", bound=dict[str, Any])

# A node function receives state and returns an update dict, Command, or Send.
# Use Sequence instead of list[...] for Python 3.10 compatibility.
NodeFn = Callable[
    [StateT],
    "dict[str, Any] | Sequence[Any] | Any | None",
]
AsyncNodeFn = Callable[
    [StateT],
    "Awaitable[dict[str, Any] | Sequence[Any] | Any | None]",
]

#: A ``Send`` or ``Command`` object (imported lazily to avoid cycles).
SendOrCommand = Any


@dataclass
class NodeDefinition(Generic[StateT]):
    """Definition of a single graph node.

    Attributes:
        name: Unique node name within the graph.
        fn: The node function or ``AgentNode`` instance.
        metadata: Arbitrary metadata (tags, description, tracing info).
        retry_policy: Optional retry configuration.
        timeout: Optional execution timeout in seconds.
    """

    name: str
    fn: NodeFn[StateT] | AsyncNodeFn[StateT] | AgentNode[StateT]
    metadata: dict[str, Any] = field(default_factory=dict)
    retry_policy: dict[str, Any] | None = None
    timeout: float | None = None


class AgentNode(Generic[StateT]):
    """A graph node with lifecycle hooks.

    Unlike plain callables, ``AgentNode`` provides three hooks that let you
    inject behaviour before, during, and after execution.

    Hooks
    =====

    ``before_node(state) -> state | None``
        Called before execution. Can modify state before passing to ``execute``.
    ``execute(state) -> update | Command | Send | None``
        Core execution logic. Must return a state update dict, ``Command``,
        ``Send``, or ``None``.
    ``after_node(state, result) -> state | None``
        Called after execution. Receives both original state and the result.

    Usage::

        class MyNode(AgentNode):
            def before_node(self, state):
                return {**state, "_started": True}

            def execute(self, state):
                return {"result": transform(state["input"])}

            def after_node(self, state, result):
                log(f"Node completed, result keys: {result.keys()}")
    """

    def __init__(self, name: str | None = None, **kwargs: Any) -> None:
        self._name = name
        self._metadata: dict[str, Any] = kwargs.pop("metadata", {})

    def before_node(self, state: StateT) -> StateT | None:
        """Hook: called before ``execute``. Return modified state or ``None``."""
        return None

    def execute(
        self, state: StateT
    ) -> dict[str, Any] | list[SendOrCommand] | SendOrCommand | None:
        """Core execution hook. Must be overridden by subclasses."""
        msg = "AgentNode subclasses must implement execute()"
        raise NotImplementedError(msg)

    def after_node(
        self,
        state: StateT,
        result: dict[str, Any] | list[SendOrCommand] | SendOrCommand | None,
    ) -> None:
        """Hook: called after ``execute`` with both state and result."""

    def _to_definition(
        self, name: str, *, metadata: dict[str, Any] | None = None
    ) -> NodeDefinition[StateT]:
        """Convert this ``AgentNode`` to a ``NodeDefinition``."""
        merged_meta = dict(self._metadata)
        if metadata:
            merged_meta.update(metadata)
        return NodeDefinition(
            name=name or self._name or type(self).__name__,
            fn=self,
            metadata=merged_meta,
        )


def node(
    fn: NodeFn[StateT] | type[AgentNode[StateT]] | None = None,
    *,
    name: str | None = None,
    **kwargs: Any,
) -> (
    NodeFn[StateT]
    | type[AgentNode[StateT]]
    | Callable[[NodeFn[StateT]], NodeFn[StateT]]
    | Callable[[type[AgentNode[StateT]]], type[AgentNode[StateT]]]
):
    """Decorator that registers a function or class as a graph node.

    Can be used as a bare decorator::

        @node
        def my_node(state): ...

    Or with arguments::

        @node(name="custom_name")
        def my_node(state): ...
    """

    def _wrap_fn(f: NodeFn[StateT]) -> NodeFn[StateT]:
        f._is_graph_node = True  # type: ignore[attr-defined]
        if name:
            f._node_name = name  # type: ignore[attr-defined]
        return f

    def _wrap_cls(cls: type[AgentNode[StateT]]) -> type[AgentNode[StateT]]:
        cls._is_graph_node = True  # type: ignore[attr-defined]
        cls._node_name = name or cls.__name__  # type: ignore[attr-defined]
        return cls

    if fn is not None:
        if isinstance(fn, type) and issubclass(fn, AgentNode):
            return _wrap_cls(fn)
        if callable(fn):
            return _wrap_fn(fn)

    # Called with arguments: return a decorator
    def _decorator(
        f: NodeFn[StateT] | type[AgentNode[StateT]],
    ) -> NodeFn[StateT] | type[AgentNode[StateT]]:
        if isinstance(f, type) and issubclass(f, AgentNode):
            return _wrap_cls(f)
        return _wrap_fn(f)  # type: ignore[return-value]

    return _decorator


__all__ = [
    "AgentNode",
    "NodeDefinition",
    "node",
]