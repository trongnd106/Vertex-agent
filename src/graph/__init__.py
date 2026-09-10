"""Vertex Agent Graph System — a powerful agent graph framework.

Built on the insights from LangGraph's Pregel algorithm, deepagents'
middleware architecture, and orchestrator's task-driven design.

## Package Structure

- ``builder`` — ``StateGraph`` fluent builder (add_node, add_edge, compile)
- ``runtime`` — ``CompiledGraph`` + ``PregelLoop`` execution engine
- ``channels`` — Channel-based state management (LastValue, Topic, etc.)
- ``node`` — ``AgentNode`` with lifecycle hooks, ``@node`` decorator
- ``types`` — Core types: Command, Send, Interrupt, RetryPolicy, etc.
- ``reducers`` — Reducer functions (add_messages, concat)
- ``errors`` — Error handling, retry, error handler registry
- ``subgraph`` — Subgraph support (nested graphs)
- ``visualization`` — Mermaid graph generation, debug tracing
- ``integration`` — DeepAgents integration layer

## Quick Start

.. code-block:: python

    from src.graph.builder import END, START, StateGraph
    from src.graph.integration import build_react_graph

    # Build a ReAct agent
    class AgentState(TypedDict):
        messages: list

    graph = build_react_graph(AgentState)
    result = graph.invoke({"messages": [{"role": "user", "content": "Hello"}]})

## Key Design Decisions

1. **Builder → Runtime separation**: ``StateGraph`` constructs the topology;
   ``compile()`` produces a ``CompiledGraph`` for execution. This mirrors
   LangGraph's separation of concerns.

2. **Channel-based state**: Each state field is backed by a ``BaseChannel``
   that controls update semantics (overwrite, accumulate, reduce). Channel
   versioning drives the scheduling algorithm.

3. **Pregel-inspired execution**: The ``PregelLoop`` implements the BSP
   (Bulk Synchronous Parallel) model: Plan → Execute → Update per step.

4. **DeepAgents integration**: Our ``StateGraph`` can optionally delegate
   to ``create_deep_agent`` for the full middleware stack, while keeping
   our uniform interface.
"""

from src.graph.builder import StateGraph
from src.graph.types import END, START
from src.graph.channels import (
    BaseChannel,
    BinaryOperatorAggregate,
    EphemeralValue,
    LastValue,
    Topic,
)
from src.graph.errors import (
    GraphError,
    MaxRetriesExceeded,
    RetryableNode,
    with_retry,
)
try:
    from src.graph.integration import (
        build_from_deep_agent,
        build_react_graph,
        build_sequential_graph,
    )
except ImportError:
    # deepagents not available
    build_from_deep_agent = None  # type: ignore[assignment]
    build_react_graph = None  # type: ignore[assignment]
    build_sequential_graph = None  # type: ignore[assignment]
from src.graph.node import AgentNode, NodeDefinition, node
from src.graph.reducers import add_messages, concat
from src.graph.runtime import CompiledGraph, PregelLoop
from src.graph.subgraph import SubgraphNode, subgraph_node, wrap_as_node
from src.graph.types import Command, Interrupt, RetryPolicy, Send, StreamChunk, StreamMode
from src.graph.visualization import GraphDebugger, draw_mermaid

__all__ = [
    # Builder
    "END",
    "START",
    "StateGraph",
    # Channels
    "BaseChannel",
    "BinaryOperatorAggregate",
    "EphemeralValue",
    "LastValue",
    "Topic",
    # Runtime
    "CompiledGraph",
    "PregelLoop",
    # Node
    "AgentNode",
    "NodeDefinition",
    "node",
    # Types
    "Command",
    "Interrupt",
    "Send",
    "StreamChunk",
    "StreamMode",
    # Errors
    "GraphError",
    "MaxRetriesExceeded",
    "RetryPolicy",
    "RetryableNode",
    "with_retry",
    # Reducers
    "add_messages",
    "concat",
    # Subgraph
    "SubgraphNode",
    "subgraph_node",
    "wrap_as_node",
    # Visualization
    "GraphDebugger",
    "draw_mermaid",
    # Integration
    "build_from_deep_agent",
    "build_react_graph",
    "build_sequential_graph",
]