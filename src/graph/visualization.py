"""Graph visualization and debugging utilities.

Generates Mermaid.js diagrams from ``StateGraph`` definitions and provides
debugging tools for inspecting graph execution.

Inspired by LangGraph's ``pregel/debug.py`` and ``pregel/_draw.py``.

Usage::

    from src.graph.builder import StateGraph
    from src.graph.visualization import draw_mermaid

    builder = StateGraph(MyState)
    # ... add nodes and edges ...
    graph = builder.compile()
    print(draw_mermaid(graph))
"""

from __future__ import annotations

from typing import Any

from src.graph.runtime import CompiledGraph
from src.graph.types import END, START


def draw_mermaid(graph: CompiledGraph[Any]) -> str:
    """Generate a Mermaid.js flow chart from a compiled graph.

    Args:
        graph: The compiled graph to visualise.

    Returns:
        A Mermaid ``flowchart TD`` string.
    """
    lines: list[str] = ["flowchart TD"]
    node_ids: dict[str, str] = {}

    # Assign short IDs to nodes
    for i, node_name in enumerate(graph.nodes):
        safe_id = _safe_id(node_name)
        node_ids[node_name] = safe_id

    # Add node declarations
    for node_name in graph.nodes:
        safe_id = node_ids[node_name]
        label = _format_node_label(node_name)
        lines.append(f"    {safe_id}[{label}]")

    # Add edges from the compiled graph's internal state
    # (We infer edges from node names and their connected neighbours)
    edges = _infer_edges(graph)
    for source, target in edges:
        if source in node_ids and target in node_ids:
            lines.append(f"    {node_ids[source]} --> {node_ids[target]}")

    return "\n".join(lines)


def draw_mermaid_png(graph: CompiledGraph[Any]) -> str:
    """Generate a Mermaid URL that renders as PNG (via mermaid.ink).

    Args:
        graph: The compiled graph to visualise.

    Returns:
        A URL to a rendered Mermaid diagram.
    """
    mermaid_code = draw_mermaid(graph)
    import urllib.parse
    encoded = urllib.parse.quote(mermaid_code)
    return f"https://mermaid.ink/img/{encoded}"


def _safe_id(name: str) -> str:
    """Convert a node name to a safe Mermaid node ID.

    Mermaid IDs must match ``[a-zA-Z0-9_]+``.
    """
    safe = "".join(c if c.isalnum() or c == "_" else "_" for c in name)
    if safe and safe[0].isdigit():
        safe = f"n{safe}"
    return safe or "unknown"


def _format_node_label(name: str) -> str:
    """Format a node name for display in Mermaid."""
    if name == "__start__":
        return "START"
    if name == "__end__":
        return "END"
    # Humanise: "my_function_node" -> "My Function Node"
    return name.replace("_", " ").title()


def _infer_edges(graph: CompiledGraph[Any]) -> list[tuple[str, str]]:
    """Infer edges from the compiled graph's node connections.

    Uses the graph's internal edge list, conditional edges, entry point,
    and finish points to reconstruct the full topology.
    """
    edges: list[tuple[str, str]] = []

    # Use edges from compiled graph internals
    internal_edges = getattr(graph, '_edges', [])
    for edge in internal_edges:
        edges.append((edge.source, edge.target))

    # Use conditional edges
    cond_edges = getattr(graph, '_conditional_edges', [])
    for ce in cond_edges:
        for target in ce.path_map.values():
            edges.append((ce.source, target))

    # Entry point edge: START -> entry
    entry = getattr(graph, '_entry_point', None)
    if entry and entry in graph.nodes:
        edges.insert(0, (START, entry))

    # Finish point edges -> END
    finish = getattr(graph, '_finish_points', [])
    for fp in finish:
        if fp in graph.nodes:
            edges.append((fp, END))

    return edges


# ── Debug utilities ──────────────────────────────────────────────────


class GraphDebugger:
    """Debug helper that records step-by-step execution details.

    Usage::

        debugger = GraphDebugger()
        result = graph.invoke(input_data)
        print(debugger.format_trace())
    """

    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []

    def record_event(
        self,
        event_type: str,
        node: str,
        step: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Record a debug event.

        Args:
            event_type: Type of event (node_start, node_end, error, etc.).
            node: Name of the node.
            step: Step number.
            details: Optional details dict.
        """
        self._events.append(
            {
                "type": event_type,
                "node": node,
                "step": step,
                "details": details or {},
            }
        )

    def format_trace(self) -> str:
        """Format the debug trace as a readable string."""
        lines = ["=== Graph Execution Trace ==="]
        for event in self._events:
            indent = "  " * event["step"]
            lines.append(
                f"{indent}[Step {event['step']}] {event['node']}: {event['type']}"
            )
            if event["details"]:
                for key, value in event["details"].items():
                    lines.append(f"{indent}  {key}: {str(value)[:200]}")
        return "\n".join(lines)

    @property
    def events(self) -> list[dict[str, Any]]:
        return list(self._events)

    def clear(self) -> None:
        """Clear all recorded events."""
        self._events.clear()


__all__ = [
    "GraphDebugger",
    "draw_mermaid",
    "draw_mermaid_png",
]