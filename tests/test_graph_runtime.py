"""Tests for ``src.graph.runtime`` — compiled graph execution."""

from typing import TypedDict

import pytest

from src.graph.builder import StateGraph
from src.graph.types import END, START
from src.graph.node import node
from src.graph.types import Command, Send, StreamChunk, StreamMode


# ── Test schemas ──────────────────────────────────────────────────────


class CalcState(TypedDict):
    messages: list
    value: int
    history: list


class SimpleMessages(TypedDict):
    messages: list


# ── Test node functions ───────────────────────────────────────────────


def add_one(state: CalcState) -> dict:
    return {"value": state.get("value", 0) + 1}


def double(state: CalcState) -> dict:
    return {"value": state.get("value", 0) * 2}


def record(state: CalcState) -> dict:
    history = state.get("history", [])
    history.append(state.get("value", 0))
    return {"history": history}


def conditional_router(state: CalcState) -> str:
    val = state.get("value", 0)
    if val < 5:
        return "increment"
    return "done"


@node
def say_hello(state: SimpleMessages) -> dict:
    return {"messages": [{"role": "assistant", "content": "Hello!"}]}


# ── CompiledGraph tests ───────────────────────────────────────────────


class TestCompiledGraph:
    def test_invoke_returns_state(self):
        """invoke() returns the final state."""
        g = StateGraph(CalcState)
        g.add_node("increment", add_one)
        g.set_entry_point("increment")
        cg = g.compile()
        result = cg.invoke({"value": 0})
        assert "value" in result

    def test_invoke_single_node(self):
        """A single node graph executes its node."""
        g = StateGraph(CalcState)
        g.add_node("add", add_one)
        g.set_entry_point("add")
        cg = g.compile()
        result = cg.invoke({"value": 0})
        assert result.get("value") == 1

    def test_invoke_two_nodes(self):
        """Two sequential nodes execute in order."""
        g = StateGraph(CalcState)
        g.add_node("add", add_one)
        g.add_node("double", double)
        g.add_edge(START, "add")
        g.add_edge("add", "double")
        cg = g.compile()
        result = cg.invoke({"value": 2})
        # add(2) = 3, double(3) = 6
        assert result.get("value") == 6

    def test_invoke_three_steps(self):
        """Three-step sequential execution."""
        g = StateGraph(CalcState)
        g.add_node("add", add_one)
        g.add_node("double", double)
        g.add_node("record", record)
        g.add_edge(START, "add")
        g.add_edge("add", "double")
        g.add_edge("double", "record")
        cg = g.compile()
        result = cg.invoke({"value": 1, "history": []})
        # add(1) = 2, double(2) = 4, record = append 4 to history
        assert result.get("value") == 4
        assert result.get("history") == [4]

    def test_invoke_name(self):
        """CompiledGraph has a name."""
        g = StateGraph(CalcState)
        g.add_node("add", add_one)
        g.set_entry_point("add")
        cg = g.compile(name="my_graph")
        assert cg.name == "my_graph"

    def test_nodes_property(self):
        """nodes property returns the node map."""
        g = StateGraph(CalcState)
        g.add_node("add", add_one)
        g.add_node("double", double)
        g.set_entry_point("add")
        cg = g.compile(name="test")
        assert "add" in cg.nodes
        assert "double" in cg.nodes

    def test_invoke_with_finish_point(self):
        """Execution stops after a finish point."""
        g = StateGraph(CalcState)
        g.add_node("step1", add_one)
        g.add_node("step2", double)
        g.add_edge(START, "step1")
        g.add_edge("step1", "step2")
        g.set_finish_point("step2")
        cg = g.compile()
        result = cg.invoke({"value": 3})
        assert result.get("value") == 8  # add(3)=4, double(4)=8

    def test_stream_returns_chunks(self):
        """stream() yields StreamChunk objects."""
        g = StateGraph(CalcState)
        g.add_node("add", add_one)
        g.set_entry_point("add")
        cg = g.compile()
        chunks = list(cg.stream({"value": 0}))
        assert len(chunks) > 0
        for chunk in chunks:
            assert isinstance(chunk, StreamChunk)

    def test_stream_has_start_and_end(self):
        """stream() has start and finish chunks."""
        g = StateGraph(SimpleMessages)
        g.add_node("greet", say_hello)
        g.set_entry_point("greet")
        cg = g.compile()
        chunks = list(cg.stream({"messages": []}))
        types = [c.metadata.get("type") for c in chunks if c.metadata]
        assert "start" in types or any(c.node_name == "__start__" for c in chunks)


# ── PregelLoop tests ──────────────────────────────────────────────────


class TestPregelLoop:
    def test_resolve_next_nodes_entry(self):
        """The entry node is resolved when nothing else is scheduled."""
        g = StateGraph(CalcState)
        g.add_node("add", add_one)
        g.set_entry_point("add")
        cg = g.compile()
        result = cg.invoke({"value": 0})
        assert result.get("value") == 1


# ── Integration test: error propagation ───────────────────────────────


def test_node_error_raised():
    """A node that raises an exception propagates it."""

    def broken(state):
        raise RuntimeError("node crashed")

    g = StateGraph(CalcState)
    g.add_node("broken", broken)
    g.set_entry_point("broken")
    cg = g.compile()
    with pytest.raises(RuntimeError, match="node crashed"):
        cg.invoke({"value": 0})


# ── Edge cases ────────────────────────────────────────────────────────


def test_empty_messages():
    """Graph can handle empty message lists."""
    g = StateGraph(SimpleMessages)

    @node
    def passthrough(state):
        return state

    g.add_node("pass", passthrough)
    g.set_entry_point("pass")
    cg = g.compile()
    result = cg.invoke({"messages": []})
    assert "messages" in result