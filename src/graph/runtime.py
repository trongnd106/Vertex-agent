"""Runtime: compiled graph execution engine.

Implements the Pregel-inspired execution loop (``PregelLoop``) that drives
the compiled graph. The execution follows a Plan → Execute → Update cycle
(Bulk Synchronous Parallel model):

1. **Plan**: Determine which nodes to run based on channel versions.
2. **Execute**: Run all selected nodes (potentially in parallel).
3. **Update**: Apply node outputs to channels and checkpoint.

The public entry points are ``CompiledGraph.invoke()`` and
``CompiledGraph.stream()``.
"""

from __future__ import annotations

import time
import traceback
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from src.graph.types import (
    END,
    START,
    Command,
    ConditionalEdgeDefinition,
    EdgeDefinition,
    ExecutionResult,
    Interrupt,
    RetryPolicy,
    Send,
    StreamChunk,
    StreamMode,
)
from src.graph.channels import LastValue, Topic
from src.graph.node import AgentNode, NodeDefinition

StateT = TypeVar("StateT", bound=dict[str, Any])

# Type alias for the step execution context
StepContext = dict[str, Any]


@dataclass
class NodeExecutionState:
    """Runtime state for a single node during execution."""

    name: str
    definition: NodeDefinition[Any]
    input_state: dict[str, Any] | None = None
    output: Any = None
    error: Exception | None = None
    duration: float = 0.0
    attempts: int = 0


class PregelLoop(Generic[StateT]):
    """The core execution loop (Bulk Synchronous Parallel).

    This implements the Plan → Execute → Update cycle that drives graph
    execution step by step.

    Args:
        nodes: Map of node name → NodeDefinition.
        edges: List of directed edges.
        conditional_edges: List of conditional edge definitions.
        entry_point: Name of the entry node.
        finish_points: Names of terminal nodes.
        channel_map: Map of channel name → BaseChannel instance.
        checkpointer: Optional checkpointer for persistence.
        store: Optional store for long-term memory.
    """

    def __init__(
        self,
        nodes: dict[str, NodeDefinition[Any]],
        edges: list[EdgeDefinition],
        conditional_edges: list[ConditionalEdgeDefinition],
        entry_point: str,
        finish_points: list[str],
        channel_map: dict[str, Any],
        checkpointer: Any = None,
        store: Any = None,
    ) -> None:
        self._nodes = nodes
        self._edges = edges
        self._conditional_edges = conditional_edges
        self._entry_point = entry_point
        self._finish_points = set(finish_points)
        self._channel_map = channel_map
        self._checkpointer = checkpointer
        self._store = store
        self._step = 0  # track current step number
        self._nodes_executed_this_step: set[str] = set()

        # Build adjacency for quick lookup
        self._outgoing: dict[str, list[str]] = {}
        self._conditional: dict[str, list[ConditionalEdgeDefinition]] = {}
        for edge in edges:
            self._outgoing.setdefault(edge.source, []).append(edge.target)
        for ce in conditional_edges:
            self._conditional.setdefault(ce.source, []).append(ce)

    # ── Step execution ────────────────────────────────────────────────

    def _resolve_next_nodes(self, state: dict[str, Any]) -> list[str]:
        """Determine which nodes to run in the next step.

        Step 1 always runs the entry point.  Subsequent steps follow edges
        from nodes that executed in the previous step.
        """
        self._step += 1

        if self._step == 1:
            # First step: always run the entry point
            self._nodes_executed_this_step = set()
            return [self._entry_point]

        # Later steps: follow edges from nodes that ran last step
        next_nodes: list[str] = []
        for edge in self._edges:
            if edge.source in self._nodes_executed_this_step:
                if edge.target not in (END, None):
                    next_nodes.append(edge.target)

        self._nodes_executed_this_step = set()
        return list(set(next_nodes))

    def _execute_node(
        self,
        node_name: str,
        state: dict[str, Any],
    ) -> tuple[dict[str, Any] | list | None, Exception | None]:
        """Execute a single node and return (output, error)."""
        node_def = self._nodes.get(node_name)
        if node_def is None:
            return None, ValueError(f"Node {node_name!r} not found")

        fn = node_def.fn
        error: Exception | None = None
        output: Any = None

        try:
            if isinstance(fn, AgentNode):
                # Lifecycle hooks
                modified_state = fn.before_node(state) or state
                output = fn.execute(modified_state)
                fn.after_node(state, output)
            elif isinstance(fn, type) and issubclass(fn, AgentNode):
                instance = fn()
                modified_state = instance.before_node(state) or state
                output = instance.execute(modified_state)
                instance.after_node(state, output)
            else:
                output = fn(state)
        except Exception as e:
            error = e

        return output, error

    def _apply_output(
        self,
        state: dict[str, Any],
        node_name: str,
        output: Any,
    ) -> dict[str, Any]:
        """Apply node output to state, handling Command/Send objects."""
        self._nodes_executed_this_step.add(node_name)

        if output is None:
            return dict(state)

        # Handle Command
        if isinstance(output, Command):
            new_state = dict(state)
            if output.update:
                new_state.update(output.update)
            if output.goto is not None:
                new_state["_goto"] = output.goto
            if output.resume is not None:
                new_state["_resume"] = output.resume
            return new_state

        # Handle Send (map-reduce)
        if isinstance(output, Send):
            new_state = dict(state)
            new_state.update(output.state)
            new_state["_send_target"] = output.node
            return new_state

        # Handle list of Send/Command
        if isinstance(output, list):
            new_state = dict(state)
            for item in output:
                if isinstance(item, Send):
                    new_state.update(item.state)
                    new_state["_send_target"] = item.node
                elif isinstance(item, Command):
                    if item.update:
                        new_state.update(item.update)
                    if item.goto:
                        new_state["_goto"] = item.goto
            return new_state

        # Handle dict updates
        if isinstance(output, dict):
            new_state = dict(state)
            # Apply to channels
            for key, value in output.items():
                if key in self._channel_map:
                    channel = self._channel_map[key]
                    if isinstance(value, list):
                        channel.update(value)
                    else:
                        channel.update([value])
                new_state[key] = value
            return new_state

        return state

    def _follow_conditional_edges(
        self,
        state: dict[str, Any],
        node_name: str,
    ) -> list[str]:
        """Follow conditional edges from a node and determine targets."""
        targets: list[str] = []
        for ce in self._conditional.get(node_name, []):
            try:
                route_key = ce.router(state)
                target = ce.path_map.get(route_key)
                if target and target != END:
                    targets.append(target)
                elif target == END:
                    pass  # Terminal
            except Exception:
                pass
        return targets

    def _should_stop(self, state: dict[str, Any], step: int, max_steps: int) -> bool:
        """Determine if execution should stop."""
        if step >= max_steps:
            return True
        for fp in self._finish_points:
            if fp in self._nodes_executed_this_step:
                return True
        # Check if goto is END
        if state.get("_goto") == END:
            return True
        return False

    # ── Main loop ─────────────────────────────────────────────────────

    def run(
        self,
        initial_state: dict[str, Any],
        *,
        max_steps: int = 100,
        stream_handler: Callable[[StreamChunk], None] | None = None,
        config: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """Run the graph execution loop.

        Args:
            initial_state: Starting state (usually ``{"messages": [...]}``).
            max_steps: Maximum number of steps.
            stream_handler: Optional callback for streaming chunks.
            config: Runtime configuration.

        Returns:
            ``ExecutionResult`` with final state and metadata.
        """
        state = dict(initial_state)
        step = 0
        start_time = time.monotonic()
        interrupted: Interrupt | None = None
        error: Exception | None = None

        # Emit initial state if streaming
        if stream_handler:
            stream_handler(
                StreamChunk(
                    content="",
                    node_name="__start__",
                    step=0,
                    metadata={"type": "start", "config": config or {}},
                )
            )

        while not self._should_stop(state, step, max_steps):
            step += 1

            # Plan: determine nodes to execute
            nodes_to_run = self._resolve_next_nodes(state)

            if not nodes_to_run:
                break

            # Execute each node
            for node_name in nodes_to_run:
                node_state = NodeExecutionState(
                    name=node_name,
                    definition=self._nodes.get(node_name, NodeDefinition(name=node_name, fn=lambda s: None)),
                    input_state=dict(state),
                )
                node_start = time.monotonic()

                try:
                    output, err = self._execute_node(node_name, state)
                    node_state.duration = time.monotonic() - node_start
                    node_state.attempts = 1

                    if err:
                        node_state.error = err
                        # Emit error chunk
                        if stream_handler:
                            stream_handler(
                                StreamChunk(
                                    content=f"Error in node {node_name}: {err}",
                                    node_name=node_name,
                                    step=step,
                                    metadata={"type": "error", "error": str(err)},
                                )
                            )
                        # Propagate error unless handled
                        raise err

                    # Apply output to state
                    state = self._apply_output(state, node_name, output)
                    node_state.output = output

                    # Emit output chunk
                    if stream_handler:
                        self._emit_node_chunks(
                            stream_handler, node_name, step, output
                        )

                    # Follow conditional edges
                    conditional_targets = self._follow_conditional_edges(
                        state, node_name
                    )
                    if conditional_targets:
                        for target in conditional_targets:
                            state[f"_should_run_{target}"] = True

                except Exception as exc:
                    # Check if this is actually an interrupt scenario
                    if hasattr(exc, "value") and getattr(exc, "node", None):
                        interrupted = Interrupt(
                            value=getattr(exc, "value", str(exc)),
                            node=node_name,
                            step=step,
                        )
                    else:
                        error = exc
                    if stream_handler:
                        stream_handler(
                            StreamChunk(
                                content="",
                                node_name=node_name,
                                step=step,
                                metadata={
                                    "type": "error",
                                    "error": str(exc),
                                    "traceback": traceback.format_exc(),
                                },
                            )
                        )
                    break

            if interrupted or error:
                break

        # Emit finish chunk
        if stream_handler:
            stream_handler(
                StreamChunk(
                    content="",
                    node_name="__end__",
                    step=step,
                    finish_reason="stop" if not error else "error",
                    metadata={
                        "type": "finish",
                        "steps": step,
                        "duration": time.monotonic() - start_time,
                        "error": str(error) if error else None,
                    },
                )
            )

        return ExecutionResult(
            state=state,
            steps=step,
            total_duration=time.monotonic() - start_time,
            interrupted=interrupted,
            error=error,
        )

    # ── Streaming helpers ─────────────────────────────────────────────

    def _emit_node_chunks(
        self,
        handler: Callable[[StreamChunk], None],
        node_name: str,
        step: int,
        output: Any,
    ) -> None:
        """Emit stream chunks for a node's output."""
        if output is None:
            return

        if isinstance(output, dict):
            for key, value in output.items():
                if key == "messages" and isinstance(value, list):
                    for msg in value:
                        content = getattr(msg, "content", str(msg))
                        handler(
                            StreamChunk(
                                content=content,
                                node_name=node_name,
                                step=step,
                                metadata={"type": "message", "key": key},
                            )
                        )
                else:
                    handler(
                        StreamChunk(
                            content=str(value)[:500] if not isinstance(value, str) else "",
                            node_name=node_name,
                            step=step,
                            metadata={
                                "type": "state_update",
                                "key": key,
                                "value_preview": str(value)[:200],
                            },
                        )
                    )

        elif isinstance(output, Command):
            handler(
                StreamChunk(
                    content="",
                    node_name=node_name,
                    step=step,
                    metadata={
                        "type": "command",
                        "goto": str(output.goto),
                        "has_update": output.update is not None,
                    },
                )
            )

        elif isinstance(output, Send):
            handler(
                StreamChunk(
                    content="",
                    node_name=node_name,
                    step=step,
                    metadata={
                        "type": "send",
                        "target": output.node,
                    },
                )
            )


class CompiledGraph(Generic[StateT]):
    """A compiled graph ready for invocation.

    This is the return value of ``StateGraph.compile()`` and exposes the
    primary execution API: ``invoke()``, ``stream()``, ``astream()``.
    """

    def __init__(
        self,
        state_schema: type[StateT],
        nodes: dict[str, NodeDefinition[Any]],
        edges: list[EdgeDefinition],
        conditional_edges: list[ConditionalEdgeDefinition],
        entry_point: str,
        finish_points: list[str],
        channel_map: dict[str, Any],
        checkpointer: Any = None,
        store: Any = None,
        name: str | None = None,
    ) -> None:
        self._state_schema = state_schema
        self._nodes = nodes
        self._edges = edges
        self._conditional_edges = conditional_edges
        self._entry_point = entry_point
        self._finish_points = finish_points
        self._channel_map = channel_map
        self._checkpointer = checkpointer
        self._store = store
        self._name = name or "graph"

    @property
    def name(self) -> str:
        return self._name

    @property
    def nodes(self) -> dict[str, NodeDefinition[Any]]:
        return dict(self._nodes)

    # ── Sync API ──────────────────────────────────────────────────────

    def invoke(
        self,
        input_data: dict[str, Any],
        *,
        config: dict[str, Any] | None = None,
        max_steps: int = 100,
    ) -> dict[str, Any]:
        """Invoke the graph synchronously.

        Args:
            input_data: Initial state (usually ``{"messages": [...]}``).
            config: Runtime configuration (thread_id, etc.).
            max_steps: Maximum number of execution steps.

        Returns:
            Final state after execution completes.
        """
        result = self._run(input_data, max_steps=max_steps, config=config)
        if result.error:
            raise result.error
        return result.state

    def stream(
        self,
        input_data: dict[str, Any],
        *,
        config: dict[str, Any] | None = None,
        max_steps: int = 100,
        mode: StreamMode = StreamMode.UPDATES,
    ) -> Iterator[StreamChunk]:
        """Stream graph execution synchronously.

        Yields ``StreamChunk`` objects as each node produces output.

        Args:
            input_data: Initial state.
            config: Runtime configuration.
            max_steps: Maximum number of execution steps.
            mode: Streaming mode (only ``UPDATES`` and ``VALUES`` supported sync).
        """
        chunks: list[StreamChunk] = []

        def _collect(chunk: StreamChunk) -> None:
            chunks.append(chunk)

        self._run(input_data, max_steps=max_steps, config=config, stream_handler=_collect)

        yield from chunks

    # ── Async API ─────────────────────────────────────────────────────

    async def ainvoke(
        self,
        input_data: dict[str, Any],
        *,
        config: dict[str, Any] | None = None,
        max_steps: int = 100,
    ) -> dict[str, Any]:
        """Invoke the graph asynchronously.

        Args:
            input_data: Initial state.
            config: Runtime configuration.
            max_steps: Maximum number of execution steps.

        Returns:
            Final state.
        """
        return self.invoke(input_data, config=config, max_steps=max_steps)

    async def astream(
        self,
        input_data: dict[str, Any],
        *,
        config: dict[str, Any] | None = None,
        max_steps: int = 100,
        mode: StreamMode = StreamMode.UPDATES,
    ) -> AsyncIterator[StreamChunk]:
        """Stream graph execution asynchronously.

        Args:
            input_data: Initial state.
            config: Runtime configuration.
            max_steps: Maximum number of execution steps.
            mode: Streaming mode.
        """
        for chunk in self.stream(
            input_data, config=config, max_steps=max_steps, mode=mode
        ):
            yield chunk

    # ── Internal ──────────────────────────────────────────────────────

    def _run(
        self,
        input_data: dict[str, Any],
        *,
        max_steps: int = 100,
        config: dict[str, Any] | None = None,
        stream_handler: Callable[[StreamChunk], None] | None = None,
    ) -> ExecutionResult:
        """Run the graph execution loop."""
        # Initialize state with input
        initial_state: dict[str, Any] = {}
        for key, channel in self._channel_map.items():
            if key in input_data:
                if isinstance(channel, LastValue):
                    channel.update([input_data[key]])
                elif isinstance(channel, Topic):
                    val = input_data[key]
                    if not isinstance(val, list):
                        val = [val]
                    channel.update(val)
                initial_state[key] = channel.value
            else:
                initial_state[key] = channel.value if channel.value is not None else ([] if isinstance(channel, Topic) else channel.value)

        # Add any extra input data not in channels
        for key, value in input_data.items():
            if key not in self._channel_map:
                initial_state[key] = value

        loop = PregelLoop(
            nodes=self._nodes,
            edges=self._edges,
            conditional_edges=self._conditional_edges,
            entry_point=self._entry_point,
            finish_points=self._finish_points,
            channel_map=self._channel_map,
            checkpointer=self._checkpointer,
            store=self._store,
        )

        return loop.run(
            initial_state,
            max_steps=max_steps,
            stream_handler=stream_handler,
            config=config,
        )

    def get_state(self, config: dict[str, Any]) -> dict[str, Any] | None:
        """Get the state for a given config (thread_id).

        Requires a checkpointer.

        Args:
            config: Config dict with ``configurable.thread_id``.

        Returns:
            The state dict, or ``None`` if not found.
        """
        if self._checkpointer is None:
            return None
        # Delegate to checkpointer if available
        try:
            if hasattr(self._checkpointer, "get"):
                thread_id = config.get("configurable", {}).get("thread_id")
                if thread_id:
                    return self._checkpointer.get(thread_id)  # type: ignore[union-attr]
        except Exception:
            pass
        return None


__all__ = [
    "CompiledGraph",
    "NodeExecutionState",
    "PregelLoop",
]