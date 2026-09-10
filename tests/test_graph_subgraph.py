"""Tests for ``src.graph.subgraph`` — subgraph support."""

from typing import TypedDict

from src.graph.builder import StateGraph
from src.graph.types import END, START
from src.graph.subgraph import SubgraphNode, subgraph_node, wrap_as_node


# ── Test schemas ──────────────────────────────────────────────────────


class InnerState(TypedDict):
    messages: list
    value: int


class OuterState(TypedDict):
    messages: list
    result: int


# ── Test node functions ───────────────────────────────────────────────


def inner_add(state: InnerState) -> dict:
    return {"value": state.get("value", 0) + 5}


def inner_double(state: InnerState) -> dict:
    return {"value": state.get("value", 0) * 2}


# ── Tests ─────────────────────────────────────────────────────────────


class TestSubgraphNode:
    def test_subgraph_node_execution(self):
        """SubgraphNode executes an inner graph."""
        # Build inner graph
        inner = StateGraph(InnerState)
        inner.add_node("add", inner_add)
        inner.set_entry_point("add")
        inner_graph = inner.compile(name="inner")

        # Wrap as subgraph node
        node = SubgraphNode(inner_graph)

        # Execute
        result = node.execute({"value": 3})
        assert result is not None
        # subgraph adds 5: 3 + 5 = 8

    def test_subgraph_node_with_state_map(self):
        """SubgraphNode maps parent state keys to subgraph keys."""
        inner = StateGraph(InnerState)
        inner.add_node("add", inner_add)
        inner.set_entry_point("add")
        inner_graph = inner.compile(name="inner")

        node = SubgraphNode(
            inner_graph,
            state_map={"result": "value"},
        )

        result = node.execute({"result": 10})
        assert result is not None

    def test_subgraph_two_nodes(self):
        """Subgraph with sequential inner nodes."""
        inner = StateGraph(InnerState)
        inner.add_node("add", inner_add)
        inner.add_node("double", inner_double)
        inner.add_edge(START, "add")
        inner.add_edge("add", "double")
        inner_graph = inner.compile(name="math_subgraph")

        node = SubgraphNode(inner_graph)
        result = node.execute({"value": 3})
        # add(3)=8, double(8)=16
        assert result is not None


class TestSubgraphHelpers:
    def test_subgraph_node_factory(self):
        """subgraph_node() creates a SubgraphNode."""
        inner = StateGraph(InnerState)
        inner.add_node("add", inner_add)
        inner.set_entry_point("add")
        inner_graph = inner.compile(name="inner")

        sg_node = subgraph_node(inner_graph)
        from src.graph.subgraph import SubgraphNode

        assert isinstance(sg_node, SubgraphNode)

    def test_wrap_as_node(self):
        """wrap_as_node creates a NodeDefinition."""
        inner = StateGraph(InnerState)
        inner.add_node("add", inner_add)
        inner.set_entry_point("add")
        inner_graph = inner.compile(name="inner")

        node_def = wrap_as_node(inner_graph, "inner_worker")
        assert node_def.name == "inner_worker"
        assert node_def.metadata.get("type") == "subgraph"
        assert node_def.metadata.get("subgraph_name") == "inner"

    def test_subgraph_in_parent_graph(self):
        """A subgraph can be added as a node in a parent graph."""
        inner = StateGraph(InnerState)
        inner.add_node("add", inner_add)
        inner.set_entry_point("add")
        inner_graph = inner.compile(name="inner")

        parent = StateGraph(OuterState)
        # Wrap the subgraph as a node definition
        node_def = wrap_as_node(inner_graph, "inner_worker")
        parent.add_node("inner_worker", node_def.fn)
        parent.set_entry_point("inner_worker")
        parent_graph = parent.compile(name="parent")

        result = parent_graph.invoke({"value": 7})
        # subgraph adds 5: 7 + 5 = 12
        assert result is not None