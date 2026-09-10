"""StateGraph builder — the entry point for constructing agent graphs.

Inspired by LangGraph's ``StateGraph`` (``langgraph/graph/state.py``) and
adapted for the vertex-agent's orchestration needs. The builder follows a
fluent API::

    builder = StateGraph(AgentState)
    builder.add_node("llm", llm_node)
    builder.add_node("tools", tool_node)
    builder.add_edge("llm", "tools")
    builder.add_conditional_edges("tools", should_continue, {"continue": "llm", "end": END})
    builder.set_entry_point("llm")
    graph = builder.compile()
    result = graph.invoke({"messages": [HumanMessage("hello")]})
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Generic, TypeVar

from src.graph.channels import channel_for_field
from src.graph.node import AgentNode, NodeDefinition
from src.graph.runtime import CompiledGraph
from src.graph.types import (
    END,
    START,
    ConditionalEdgeDefinition,
    EdgeDefinition,
)

StateT = TypeVar("StateT", bound=dict[str, Any])


class StateGraph(Generic[StateT]):
    """Builder for constructing agent state graphs.

    A ``StateGraph`` defines the topology of an agent — its nodes, edges,
    and state schema — and then ``compile()``\s it into a ``CompiledGraph``
    ready for invocation.

    Args:
        state_schema: A ``TypedDict`` or dataclass that defines the graph's
            state fields. Each field gets an automatically-assigned channel
            type based on its annotation (``LastValue`` by default,
            ``Topic`` for lists, ``BinaryOperatorAggregate`` for reducers).
    """

    def __init__(self, state_schema: type[StateT]) -> None:
        self._state_schema = state_schema
        self._nodes: dict[str, NodeDefinition] = {}
        self._edges: list[EdgeDefinition] = []
        self._conditional_edges: list[ConditionalEdgeDefinition] = []
        self._entry_point: str | None = None
        self._finish_points: list[str] = []

    # ── Node API ──────────────────────────────────────────────────────

    def add_node(
        self,
        key: str,
        action: Callable[..., Any] | AgentNode[Any],
        *,
        metadata: dict[str, Any] | None = None,
    ) -> StateGraph[StateT]:
        """Add a node to the graph.

        Args:
            key: Unique node name.
            action: The callable or ``AgentNode`` instance to execute.
            metadata: Optional metadata (tags, description, etc.).

        Returns:
            Self for chaining.
        """
        if key in (START, END):
            msg = f"Cannot use reserved node name: {key!r}"
            raise ValueError(msg)
        if key in self._nodes:
            msg = f"Node {key!r} already exists"
            raise ValueError(msg)

        if isinstance(action, AgentNode):
            node_def = action._to_definition(key, metadata=metadata)
        else:
            node_def = NodeDefinition(
                name=key,
                fn=action,
                metadata=metadata or {},
            )
        self._nodes[key] = node_def
        return self

    def add_edge(self, source: str, target: str) -> StateGraph[StateT]:
        """Add a directed edge from *source* to *target*.

        Args:
            source: Source node name.
            target: Target node name (or ``END``).

        Returns:
            Self for chaining.
        """
        if source == START:
            self._entry_point = target
            return self
        self._edges.append(EdgeDefinition(source, target))
        if target == END:
            self._finish_points.append(source)
        return self

    def add_conditional_edges(
        self,
        source: str,
        router: Callable[[dict[str, Any]], str],
        path_map: dict[str, str],
    ) -> StateGraph[StateT]:
        """Add conditional edges from *source* based on a router function.

        The ``router`` receives the current state and returns a key from
        ``path_map``; the corresponding target node is then scheduled.

        Args:
            source: Source node name.
            router: Function that inspects state and returns a routing key.
            path_map: Mapping from routing key to target node name.

        Returns:
            Self for chaining.
        """
        self._conditional_edges.append(
            ConditionalEdgeDefinition(source, router, path_map)
        )
        return self

    def set_entry_point(self, node: str) -> StateGraph[StateT]:
        """Set the entry (start) node.

        Args:
            node: Node name where execution begins.
        """
        self._entry_point = node
        return self

    def set_finish_point(self, node: str) -> StateGraph[StateT]:
        """Set a finish point: execution ends after this node.

        Args:
            node: Node name after which execution stops.
        """
        self._finish_points.append(node)
        if node not in [e.source for e in self._edges]:
            self._edges.append(EdgeDefinition(node, END))
        return self

    def get_node(self, key: str) -> NodeDefinition | None:
        """Get a node definition by name.

        Args:
            key: Node name.

        Returns:
            The ``NodeDefinition``, or ``None`` if not found.
        """
        return self._nodes.get(key)

    @property
    def nodes(self) -> dict[str, NodeDefinition]:
        """All registered nodes."""
        return dict(self._nodes)

    @property
    def edges(self) -> list[EdgeDefinition]:
        """All registered edges."""
        return list(self._edges)

    @property
    def conditional_edges(self) -> list[ConditionalEdgeDefinition]:
        """All registered conditional edges."""
        return list(self._conditional_edges)

    # ── Validation ────────────────────────────────────────────────────

    def _validate(self) -> None:
        """Validate graph topology before compilation."""
        if not self._entry_point and not self._edges:
            msg = "No entry point set. Call set_entry_point() or add_edge(START, node)."
            raise ValueError(msg)

        # Check all referenced nodes exist
        all_refs: set[str] = set()
        if self._entry_point:
            all_refs.add(self._entry_point)
        for edge in self._edges:
            if edge.source != START:
                all_refs.add(edge.source)
            if edge.target != END:
                all_refs.add(edge.target)
        for ce in self._conditional_edges:
            all_refs.add(ce.source)
            for target in ce.path_map.values():
                if target != END:
                    all_refs.add(target)

        missing = all_refs - set(self._nodes.keys())
        if missing:
            msg = f"Nodes referenced but not defined: {missing}"
            raise ValueError(msg)

    # ── Schema channel mapping ────────────────────────────────────────

    def _build_channel_map(self) -> dict[str, Any]:
        """Inspect the state schema and create channels for each field."""
        channels: dict[str, Any] = {}

        # Try TypedDict annotations first
        annotations = getattr(self._state_schema, "__annotations__", {})
        if not annotations:
            # Fall back to dataclass fields
            import dataclasses

            if dataclasses.is_dataclass(self._state_schema):
                for field_def in dataclasses.fields(self._state_schema):
                    channels[field_def.name] = channel_for_field(
                        field_def.type, field_def.name
                    )
        else:
            for field_name, field_type in annotations.items():
                channels[field_name] = channel_for_field(field_type, field_name)

        return channels

    def compile(
        self,
        *,
        checkpointer: Any = None,
        store: Any = None,
        name: str | None = None,
    ) -> CompiledGraph[StateT]:
        """Compile the graph into an executable ``CompiledGraph``.

        This performs validation, channel mapping, and builds the runtime
        representation.

        Args:
            checkpointer: Optional checkpointer for state persistence.
            store: Optional store for long-term memory.
            name: Optional graph name.

        Returns:
            A ``CompiledGraph`` ready for ``invoke()`` / ``stream()``.
        """
        self._validate()
        channel_map = self._build_channel_map()

        return CompiledGraph(
            state_schema=self._state_schema,
            nodes=self._nodes,
            edges=self._edges,
            conditional_edges=self._conditional_edges,
            entry_point=self._entry_point,
            finish_points=self._finish_points,
            channel_map=channel_map,
            checkpointer=checkpointer,
            store=store,
            name=name,
        )


__all__ = [
    "StateGraph",
]