"""Tests for ``src.graph.builder`` — StateGraph builder."""

from typing import Annotated, TypedDict

import pytest

from src.graph.builder import StateGraph
from src.graph.types import END, START
from src.graph.node import AgentNode, node
from src.graph.types import Command, Send


# ── Test state schemas ────────────────────────────────────────────────


class SimpleState(TypedDict):
    messages: list
    counter: int
    result: str


# ── Test node functions ───────────────────────────────────────────────


def increment_node(state: SimpleState) -> dict:
    return {"counter": state.get("counter", 0) + 1}


def echo_node(state: SimpleState) -> dict:
    msgs = state.get("messages", [])
    return {"result": f"Echo: {msgs[-1] if msgs else 'empty'}"}


def conditional_router(state: SimpleState) -> str:
    return "end" if state.get("counter", 0) >= 3 else "continue"


# ── Tests ─────────────────────────────────────────────────────────────


class TestStateGraph:
    def test_create_empty(self):
        """Can create a StateGraph with a schema."""
        g = StateGraph(SimpleState)
        assert g.nodes == {}

    def test_add_node(self):
        """Can add a node to the graph."""
        g = StateGraph(SimpleState)
        g.add_node("increment", increment_node)
        assert "increment" in g.nodes

    def test_add_duplicate_node_raises(self):
        """Adding a duplicate node raises ValueError."""
        g = StateGraph(SimpleState)
        g.add_node("test", increment_node)
        with pytest.raises(ValueError, match="already exists"):
            g.add_node("test", echo_node)

    def test_reserved_node_names(self):
        """START and END cannot be used as node names."""
        g = StateGraph(SimpleState)
        for reserved in (START, END):
            with pytest.raises(ValueError, match="reserved"):
                g.add_node(reserved, increment_node)

    def test_add_edge(self):
        """Can add a directed edge between nodes."""
        g = StateGraph(SimpleState)
        g.add_node("a", increment_node)
        g.add_node("b", echo_node)
        g.add_edge("a", "b")
        assert len(g.edges) == 1

    def test_add_edge_from_start_sets_entry(self):
        """add_edge(START, node) sets the entry point."""
        g = StateGraph(SimpleState)
        g.add_node("a", increment_node)
        g.add_edge(START, "a")
        # _entry_point should be set
        assert g._entry_point == "a"

    def test_set_entry_point(self):
        """set_entry_point works."""
        g = StateGraph(SimpleState)
        g.add_node("first", increment_node)
        g.set_entry_point("first")
        assert g._entry_point == "first"

    def test_set_finish_point(self):
        """set_finish_point adds a finish point."""
        g = StateGraph(SimpleState)
        g.add_node("end_node", echo_node)
        g.set_finish_point("end_node")
        assert "end_node" in g._finish_points

    def test_add_conditional_edges(self):
        """Can add conditional edges."""
        g = StateGraph(SimpleState)
        g.add_node("router", conditional_router)
        g.add_conditional_edges(
            "router",
            conditional_router,
            {"continue": "router", "end": END},
        )
        assert len(g.conditional_edges) == 1

    def test_validation_no_entry(self):
        """A graph with no edges fails validation."""
        g = StateGraph(SimpleState)
        with pytest.raises(ValueError, match="No entry point"):
            g.compile()

    def test_validation_missing_node(self):
        """A graph referencing undefined nodes fails validation."""
        g = StateGraph(SimpleState)
        g.add_node("a", increment_node)
        g.add_edge("a", "missing")  # "missing" doesn't exist
        with pytest.raises(ValueError, match="missing"):
            g.compile()

    def test_compile_returns_compiled_graph(self):
        """compile() returns a CompiledGraph."""
        g = StateGraph(SimpleState)
        g.add_node("a", increment_node)
        g.set_entry_point("a")
        cg = g.compile()
        from src.graph.runtime import CompiledGraph

        assert isinstance(cg, CompiledGraph)

    def test_compile_with_name(self):
        """Compiled graph has a name."""
        g = StateGraph(SimpleState)
        g.add_node("a", increment_node)
        g.set_entry_point("a")
        cg = g.compile(name="test_graph")
        assert cg.name == "test_graph"

    def test_get_node(self):
        """Can retrieve a node by name."""
        g = StateGraph(SimpleState)
        g.add_node("my_node", increment_node)
        nd = g.get_node("my_node")
        assert nd is not None
        assert nd.name == "my_node"

    def test_get_node_missing(self):
        """Missing node returns None."""
        g = StateGraph(SimpleState)
        assert g.get_node("ghost") is None

    def test_chaining(self):
        """add_node/add_edge return self for chaining."""
        g = StateGraph(SimpleState)
        result = (
            g.add_node("a", increment_node)
            .add_node("b", echo_node)
            .add_edge("a", "b")
        )
        assert result is g

    def test_entry_via_edge(self):
        """Entry point is inferred from edge(START, node)."""
        g = StateGraph(SimpleState)
        g.add_node("entry", increment_node)
        g.add_edge(START, "entry")  # This sets entry_point
        g.compile()  # Should pass validation

    def test_simple_graph_execution(self):
        """Compiled graph can be invoked."""
        g = StateGraph(SimpleState)
        g.add_node("counter", increment_node)
        g.set_entry_point("counter")
        cg = g.compile()
        result = cg.invoke({"counter": 0})
        assert result.get("counter") == 1

    def test_two_node_execution(self):
        """Two-node sequential graph executes correctly."""
        g = StateGraph(SimpleState)
        g.add_node("increment", increment_node)
        g.add_node("echo", echo_node)
        g.add_edge(START, "increment")
        g.add_edge("increment", "echo")
        cg = g.compile()
        result = cg.invoke({"messages": ["hello"], "counter": 0})
        assert result.get("counter") == 1


# ── @node decorator ───────────────────────────────────────────────────


class TestNodeDecorator:
    def test_bare_decorator(self):
        """@node without arguments."""
        @node
        def my_fn(state):
            return {"result": "ok"}

        assert hasattr(my_fn, "_is_graph_node")

    def test_decorator_with_name(self):
        """@node(name='x') sets custom name."""
        @node(name="custom")
        def my_fn(state):
            return {"result": "ok"}

        assert my_fn._node_name == "custom"  # type: ignore[attr-defined]

    def test_decorator_class(self):
        """@node on an AgentNode subclass."""
        @node
        class MyNode(AgentNode):
            def execute(self, state):
                return {"result": "class_exec"}

        assert hasattr(MyNode, "_is_graph_node")


# ── AgentNode class ───────────────────────────────────────────────────


class TestAgentNode:
    def test_agent_node_execute(self):
        """AgentNode execute() is called during graph execution."""

        class TestNode(AgentNode):
            def execute(self, state):
                return {"result": "from_agent_node"}

        g = StateGraph(SimpleState)
        g.add_node("agent_node", TestNode())
        g.set_entry_point("agent_node")
        cg = g.compile()
        result = cg.invoke({})
        assert result.get("result") == "from_agent_node"

    def test_agent_node_lifecycle(self):
        """AgentNode lifecycle hooks are called."""
        calls: list[str] = []

        class LifecycleNode(AgentNode):
            def before_node(self, state):
                calls.append("before")
                return {**state, "_modified": True}

            def execute(self, state):
                calls.append("execute")
                return {"lifecycle": "complete"}

            def after_node(self, state, result):
                calls.append("after")

        g = StateGraph(SimpleState)
        g.add_node("lifecycle", LifecycleNode())
        g.set_entry_point("lifecycle")
        cg = g.compile()
        cg.invoke({})
        assert calls == ["before", "execute", "after"]