"""Subgraph support for the agent graph system.

Subgraphs allow nesting graphs within graphs. Each subgraph has its own
state, channels, and nodes, but can communicate with its parent via
``Command(graph=Command.PARENT)``.

Isolation:
    - Each subgraph has its own namespace for checkpoints.
    - State changes inside a subgraph do not merge into the parent unless
      explicitly mapped.
    - Subgraphs share the parent's store and checkpointer by default.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from src.graph.builder import StateGraph
from src.graph.types import END, START
from src.graph.node import NodeDefinition
from src.graph.runtime import CompiledGraph, PregelLoop
from src.graph.types import Command, ExecutionResult

StateT = TypeVar("StateT", bound=dict[str, Any])


class SubgraphNode(Generic[StateT]):
    """A node that wraps an inner ``CompiledGraph`` as a single step.

    When the parent graph executes this node, it runs the entire subgraph
    to completion before returning control to the parent.

    Args:
        graph: The compiled subgraph to execute.
        state_map: Optional mapping of parent state keys → subgraph input
            keys, and subgraph output keys → parent state keys.
    """

    def __init__(
        self,
        graph: CompiledGraph[StateT],
        *,
        state_map: dict[str, str] | None = None,
    ) -> None:
        self._graph = graph
        self._state_map = state_map or {}
        self._reverse_map: dict[str, str] = {}
        if state_map:
            self._reverse_map = {v: k for k, v in state_map.items()}

    def execute(self, state: dict[str, Any]) -> dict[str, Any] | Command[Any]:
        """Run the subgraph with relevant state from the parent.

        Extracts the state fields the subgraph needs (via ``state_map``),
        runs the subgraph, and maps the output back.
        """
        # Build subgraph input from parent state
        sub_input: dict[str, Any] = {}
        for parent_key, sub_key in self._state_map.items():
            if parent_key in state:
                sub_input[sub_key] = state[parent_key]
        # Also pass messages by default
        if "messages" in state and "messages" not in sub_input:
            sub_input["messages"] = state["messages"]

        try:
            # Run subgraph
            sub_result = self._graph.invoke(sub_input)

            # Map subgraph output back to parent state
            output: dict[str, Any] = {}
            for sub_key, parent_key in self._reverse_map.items():
                if sub_key in sub_result:
                    output[parent_key] = sub_result[sub_key]

            # If subgraph returned a Command targeting PARENT, propagate it
            if "messages" in sub_result:
                output["messages"] = sub_result["messages"]

            return output

        except Exception as exc:
            return Command(goto="__error_handler__", update={"error": str(exc)})


def subgraph_node(
    graph: CompiledGraph[Any],
    *,
    state_map: dict[str, str] | None = None,
    name: str | None = None,
) -> SubgraphNode[Any]:
    """Create a subgraph node from a compiled graph.

    Args:
        graph: The compiled subgraph.
        state_map: Mapping from parent state key → subgraph state key.
        name: Optional node name.

    Returns:
        A ``SubgraphNode`` wrapper.
    """
    return SubgraphNode(graph, state_map=state_map)


def wrap_as_node(graph: CompiledGraph[Any], name: str) -> NodeDefinition[Any]:
    """Wrap a compiled graph as a ``NodeDefinition`` for use in a parent graph.

    Args:
        graph: The compiled subgraph.
        name: Node name in the parent graph.

    Returns:
        A ``NodeDefinition`` that executes the subgraph when invoked.
    """
    node = SubgraphNode(graph)
    return NodeDefinition(
        name=name,
        fn=node.execute,
        metadata={"type": "subgraph", "subgraph_name": graph.name},
    )


__all__ = ["SubgraphNode", "subgraph_node", "wrap_as_node"]