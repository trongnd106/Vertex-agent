"""Tests for ``src.graph.visualization`` — graph visualisation and debug."""

from typing import TypedDict

from src.graph.builder import StateGraph
from src.graph.types import END, START
from src.graph.visualization import GraphDebugger, draw_mermaid


# ── Test state ────────────────────────────────────────────────────────


class VizState(TypedDict):
    messages: list


# ── Node functions ────────────────────────────────────────────────────


def node_a(state):
    return {"messages": [{"role": "assistant", "content": "A"}]}


def node_b(state):
    return {"messages": [{"role": "assistant", "content": "B"}]}


# ── draw_mermaid ──────────────────────────────────────────────────────


class TestDrawMermaid:
    def test_returns_string(self):
        """draw_mermaid returns a string."""
        g = StateGraph(VizState)
        g.add_node("a", node_a)
        g.set_entry_point("a")
        cg = g.compile()
        output = draw_mermaid(cg)
        assert isinstance(output, str)
        assert "flowchart TD" in output

    def test_contains_node_names(self):
        """The diagram contains node names."""
        g = StateGraph(VizState)
        g.add_node("processor_a", node_a)
        g.add_node("processor_b", node_b)
        g.add_edge(START, "processor_a")
        g.add_edge("processor_a", "processor_b")
        cg = g.compile()
        output = draw_mermaid(cg)
        assert "processor_a" in output or "Processor A" in output
        assert "processor_b" in output or "Processor B" in output


# ── GraphDebugger ─────────────────────────────────────────────────────


class TestGraphDebugger:
    def test_record_event(self):
        """Can record debug events."""
        d = GraphDebugger()
        d.record_event("node_start", "processor", 1, {"input_size": 512})
        assert len(d.events) == 1
        assert d.events[0]["type"] == "node_start"
        assert d.events[0]["node"] == "processor"

    def test_format_trace(self):
        """format_trace produces text output."""
        d = GraphDebugger()
        d.record_event("node_start", "root", 0, {"msg": "starting"})
        d.record_event("node_end", "root", 0, {"result": "ok"})
        trace = d.format_trace()
        assert "Graph Execution Trace" in trace
        assert "root" in trace
        assert "node_start" in trace

    def test_clear(self):
        """clear empties the event list."""
        d = GraphDebugger()
        d.record_event("node_start", "x", 1)
        d.clear()
        assert d.events == []

    def test_events_property(self):
        """events returns a copy of the event list."""
        d = GraphDebugger()
        d.record_event("test", "n", 1)
        events = d.events
        events.append({"type": "extra"})
        # Original should be unchanged
        assert len(d.events) == 1