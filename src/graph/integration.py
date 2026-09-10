"""DeepAgents integration layer.

Bridges our custom graph system with the DeepAgents (``create_deep_agent``)
harness. This allows using our ``StateGraph`` builder with DeepAgents'
middleware, skills, memory, profiles, and tool system.

Key functions:

- ``build_deep_agent_graph()`` — creates a compiled graph via DeepAgents
  but managed through our ``StateGraph`` interface.
- ``to_deep_agent()`` — converts a ``CompiledGraph`` into a DeepAgents
  parameter set for use with ``create_deep_agent``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

# DeepAgents imports (optional — deepagents may not be installed or may require Python 3.11+)
try:
    from deepagents import create_deep_agent
    from deepagents.backends.composite import CompositeBackend
    from deepagents.backends.filesystem import FilesystemBackend
    from deepagents.backends.protocol import BackendProtocol
    from deepagents.middleware.memory import MemoryMiddleware
    from deepagents.middleware.skills import SkillsMiddleware

    _HAS_DEEPAGENTS = True
except ImportError:
    _HAS_DEEPAGENTS = False

    # Placeholder for type hints
    create_deep_agent = None  # type: ignore[assignment]
    BackendProtocol = Any  # type: ignore[assignment,misc]

from src.graph.builder import StateGraph
from src.graph.types import END, START
from src.graph.node import AgentNode, node
from src.graph.runtime import CompiledGraph
from src.graph.types import Command, StreamMode


# ── Agent node definitions ───────────────────────────────────────────


@node
def deep_agent_node(state: dict[str, Any]) -> dict[str, Any]:
    """Default agent node: processes state through an LLM.

    This is the minimal node function that makes an agent graph work.
    In production, this is replaced by DeepAgents' ``create_deep_agent``
    which wires the full middleware stack.

    Args:
        state: Current graph state (must contain ``messages``).

    Returns:
        Updated state with new messages appended.
    """
    messages = state.get("messages", [])
    if not messages:
        return state
    last = messages[-1]
    return {
        "messages": [
            {
                "role": "assistant",
                "content": f"Processed: {last.get('content', '')[:100]}",
            }
        ]
    }


@node
def tool_executor_node(state: dict[str, Any]) -> dict[str, Any]:
    """Tool execution node: runs tools called by the agent.

    Args:
        state: Current state with tool calls.

    Returns:
        State with tool results.
    """
    messages = state.get("messages", [])
    tool_results = []

    for msg in messages:
        tool_calls = getattr(msg, "tool_calls", None) or (
            msg.get("tool_calls") if isinstance(msg, dict) else None
        )
        if tool_calls:
            for tc in tool_calls:
                tool_results.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "name": tc.get("name", ""),
                        "content": f"Executed {tc.get('name', 'unknown')} with args: {tc.get('args', {})}",
                    }
                )

    if tool_results:
        return {"messages": tool_results}
    return state


@node
def should_continue(state: dict[str, Any]) -> str:
    """Router: determine if the agent should continue or stop.

    This is the classic agent loop router: if the last message has
    tool_calls, continue to the tool executor; otherwise stop.

    Args:
        state: Current graph state.

    Returns:
        Routing key: "continue" or "end".
    """
    messages = state.get("messages", [])
    if not messages:
        return "end"

    last = messages[-1]
    if isinstance(last, dict):
        tool_calls = last.get("tool_calls", [])
    else:
        tool_calls = getattr(last, "tool_calls", [])

    return "continue" if tool_calls else "end"


# ── Pre-built graph factories ────────────────────────────────────────


def build_react_graph(state_schema: type[Any]) -> CompiledGraph[Any]:
    """Build a ReAct-style agent graph:
    START -> agent -> tools -> (continue -> agent | end -> END)

    Args:
        state_schema: The state schema (must have ``messages``).

    Returns:
        A compiled graph.
    """
    builder = StateGraph(state_schema)
    builder.add_node("agent", deep_agent_node)
    builder.add_node("tools", tool_executor_node)
    builder.add_edge(START, "agent")
    builder.add_conditional_edges(
        "tools",
        should_continue,
        {"continue": "agent", "end": END},
    )
    builder.add_edge("agent", "tools")
    return builder.compile(name="react_agent")


def build_sequential_graph(
    state_schema: type[Any],
    node_list: list[tuple[str, Any]],
) -> CompiledGraph[Any]:
    """Build a sequential graph: nodes execute in order.

    Args:
        state_schema: The state schema.
        node_list: List of ``(name, fn)`` tuples in execution order.

    Returns:
        A compiled graph.
    """
    if not node_list:
        msg = "At least one node is required"
        raise ValueError(msg)

    builder = StateGraph(state_schema)
    for name, fn in node_list:
        builder.add_node(name, fn)

    # Wire sequentially
    for i in range(len(node_list) - 1):
        builder.add_edge(node_list[i][0], node_list[i + 1][0])

    builder.set_entry_point(node_list[0][0])
    builder.set_finish_point(node_list[-1][0])
    return builder.compile(name="sequential")


# ── DeepAgents integration ────────────────────────────────────────────


def to_deep_agent_params(
    graph: CompiledGraph[Any],
    *,
    model: str | Any = "openai:gpt-4o-mini",
    system_prompt: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Convert a ``CompiledGraph`` to parameters for ``create_deep_agent``.

    Extracts the node functions and configuration from our compiled graph
    and maps them to DeepAgents' middleware, tools, and subagents.

    Args:
        graph: Our compiled graph to convert.
        model: The LLM model identifier or instance.
        system_prompt: Optional system prompt.
        **kwargs: Additional arguments passed to ``create_deep_agent``.

    Returns:
        A dict of parameters suitable for ``create_deep_agent(**params)``.
    """
    params: dict[str, Any] = dict(kwargs)
    params["model"] = model

    if system_prompt:
        params["system_prompt"] = system_prompt

    # Extract custom tools from node functions
    custom_tools = []
    for node_name, node_def in graph.nodes.items():
        fn = node_def.fn
        if hasattr(fn, "__tool__"):
            tool = fn.__tool__
            if callable(tool):
                custom_tools.append(tool)

    if custom_tools:
        params["tools"] = custom_tools

    # Set checkpointer and store from graph configuration
    if hasattr(graph, "_checkpointer") and graph._checkpointer:  # type: ignore[union-attr]
        params["checkpointer"] = graph._checkpointer  # type: ignore[union-attr]
    if hasattr(graph, "_store") and graph._store:  # type: ignore[union-attr]
        params["store"] = graph._store  # type: ignore[union-attr]

    return params


def build_from_deep_agent(
    *,
    model: str | Any = "openai:gpt-4o-mini",
    system_prompt: str | None = None,
    middleware: Sequence[Any] | None = None,
    subagents: Sequence[Any] | None = None,
    skills: Sequence[str] | None = None,
    memory: Sequence[str] | None = None,
    permissions: Sequence[Any] | None = None,
    backend: Any = None,
    context_schema: type[Any] | None = None,
    tools: Sequence[Any] | None = None,
    checkpointer: Any = None,
    store: Any = None,
    **kwargs: Any,
) -> CompiledGraph[Any]:
    """Build a compiled graph through DeepAgents.

    This is the primary integration path: it delegates to
    ``create_deep_agent`` internally but wraps the result in our
    ``CompiledGraph`` interface for compatibility.

    Args:
        model: LLM model.
        system_prompt: System prompt.
        middleware: Middleware list for ``create_deep_agent``.
        subagents: Subagents for ``create_deep_agent``.
        skills: Skills sources.
        memory: Memory files.
        permissions: Filesystem permissions.
        backend: Filesystem backend.
        context_schema: Context schema for per-user namespaces.
        tools: Custom tools.
        checkpointer: Checkpointer (session persistence).
        store: Store (long-term memory).
        **kwargs: Additional DeepAgents parameters.

    Returns:
        A ``CompiledGraph`` that wraps the DeepAgents agent.

    Raises:
        ImportError: If ``deepagents`` is not installed.
    """
    if not _HAS_DEEPAGENTS:
        msg = "deepagents is not installed. Install with: pip install deepagents"
        raise ImportError(msg)

    # Build DeepAgents agent dictionary
    da_kwargs: dict[str, Any] = dict(kwargs)
    da_kwargs["model"] = model
    if system_prompt is not None:
        da_kwargs["system_prompt"] = system_prompt
    if middleware is not None:
        da_kwargs["middleware"] = list(middleware)
    if subagents is not None:
        da_kwargs["subagents"] = list(subagents)
    if skills is not None:
        da_kwargs["skills"] = list(skills)
    if memory is not None:
        da_kwargs["memory"] = list(memory)
    if permissions is not None:
        da_kwargs["permissions"] = list(permissions)
    if backend is not None:
        da_kwargs["backend"] = backend
    if context_schema is not None:
        da_kwargs["context_schema"] = context_schema
    if tools is not None:
        da_kwargs["tools"] = list(tools)
    if checkpointer is not None:
        da_kwargs["checkpointer"] = checkpointer
    if store is not None:
        da_kwargs["store"] = store
    if "debug" not in da_kwargs:
        da_kwargs["debug"] = False

    # If not provided, use sensible defaults
    if "skills" not in da_kwargs or da_kwargs["skills"] is None:
        da_kwargs["skills"] = ["/skills/"]

    # Call create_deep_agent
    deep_agent = create_deep_agent(**da_kwargs)

    # Wrap in a CompiledGraph interface
    return _wrap_deep_agent(deep_agent, name=da_kwargs.get("name"))


def _wrap_deep_agent(
    deep_agent: Any,
    name: str | None = None,
) -> CompiledGraph[Any]:
    """Wrap a DeepAgents compiled graph in our ``CompiledGraph`` interface.

    This allows using DeepAgents-produced graphs through our uniform API.

    Args:
        deep_agent: The return value of ``create_deep_agent()``.
        name: Optional name.

    Returns:
        A ``CompiledGraph`` delegating to the underlying DeepAgents graph.
    """

    class DeepAgentWrapper(CompiledGraph[Any]):
        """Adapter: makes a DeepAgents graph look like our CompiledGraph."""

        def __init__(self, da_graph: Any, wrap_name: str | None) -> None:
            # Create a minimal mock schema to satisfy CompiledGraph.__init__
            mock_schema: type[dict[str, Any]] = dict  # type: ignore[assignment]
            super().__init__(
                state_schema=mock_schema,
                nodes={},
                edges=[],
                conditional_edges=[],
                entry_point="agent",
                finish_points=[],
                channel_map={},
                name=wrap_name or "deep_agent",
            )
            self._da_graph = da_graph

        def invoke(
            self,
            input_data: dict[str, Any],
            *,
            config: dict[str, Any] | None = None,
            max_steps: int = 100,
        ) -> dict[str, Any]:
            return self._da_graph.invoke(input_data, config=config or {})

        def stream(
            self,
            input_data: dict[str, Any],
            *,
            config: dict[str, Any] | None = None,
            max_steps: int = 100,
            mode: StreamMode = StreamMode.UPDATES,
        ) -> Any:
            return self._da_graph.stream(
                input_data, config=config or {}, stream_mode=mode.value
            )

        async def ainvoke(
            self,
            input_data: dict[str, Any],
            *,
            config: dict[str, Any] | None = None,
            max_steps: int = 100,
        ) -> dict[str, Any]:
            return await self._da_graph.ainvoke(input_data, config=config or {})

        async def astream(
            self,
            input_data: dict[str, Any],
            *,
            config: dict[str, Any] | None = None,
            max_steps: int = 100,
            mode: StreamMode = StreamMode.UPDATES,
        ) -> Any:
            async for chunk in self._da_graph.astream(
                input_data, config=config or {}, stream_mode=mode.value
            ):
                yield chunk

        @property
        def nodes(self) -> dict[str, Any]:
            return {"agent": {}}

    return DeepAgentWrapper(deep_agent, name)


__all__ = [
    "build_from_deep_agent",
    "build_react_graph",
    "build_sequential_graph",
    "deep_agent_node",
    "should_continue",
    "to_deep_agent_params",
    "tool_executor_node",
]