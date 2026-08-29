"""Central deep-agent factory wiring the vertex-agent backend together.

Task 5 (Phase 5) is where ``create_deep_agent`` becomes the project's single
construction point: long-term memory (Store + ``/memory/`` backend), the
per-user context schema, the built-in filesystem backend, the Task 2 custom
tools, and (optionally) the Task 4 checkpointer are all threaded here. Tasks
6-8 consume this factory instead of calling ``create_deep_agent`` directly.

Layering notes (see `docs/phase-0-discovery.md`):

- ``store`` / ``checkpointer`` / ``system_prompt`` / ``skills`` /
  ``context_schema`` / ``backend`` are passed straight through to
  ``create_deep_agent`` (deepagents 0.7.9).
- ``backend`` defaults to the Store-backed memory filesystem
  (:func:`src.memory.memory_backend.build_memory_filesystem`), so ``/memory/``
  is a Store namespace while ``/skills/`` (and everything else) stays on the
  on-disk default route. Skills load via ``skills=["/skills/"]``.
- Tool wiring: the Task 2 custom tools (``query_order``,
  ``create_support_ticket``) **add** to the built-in filesystem/task tools,
  never replace them.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Callable

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.base import BaseStore

from deepagents import create_deep_agent
from deepagents.backends.protocol import BackendProtocol

from src.agent.context.limit_output import LimitToolOutputMiddleware
from src.agent.context.summarization import build_summarization_middleware
from src.agent.tools import create_support_ticket, query_order
from src.config.settings import get_settings
from src.memory.dreaming.enqueue import EnqueueAfterTurnMiddleware
from src.memory.memory_backend import (
    USER_CONTEXT_SCHEMA,
    UserContext,
    build_memory_filesystem,
)

MEMORY_GUIDANCE = (
    "LONG-TERM MEMORY: you have persistent cross-session memory stored as your "
    "own file /memory/notes.md (it survives across all sessions and threads).\n"
    "- At the START of a new session, read_file(\"/memory/notes.md\") first to "
    "recall the user's remembered facts and preferences.\n"
    "- During a session, whenever you learn an important, durable user fact or "
    "preference, save it by calling write_file(\"/memory/notes.md\", <the full "
    "accumulated notes, overwriting the previous content>).\n"
    "- Keep notes concise and fact-based (names, preferences, constraints); "
    "overwrite the whole file each time instead of appending duplicates."
)

#: Default user-context schema: enables per-user ``("memories", user_id)``
#: namespaces (see ``src/memory/memory_backend`` for the probe verdict).
DEFAULT_CONTEXT_SCHEMA: type[UserContext] = USER_CONTEXT_SCHEMA

#: Task 2 custom business tools added on top of the built-in tools.
DEFAULT_TOOLS: tuple[BaseTool, ...] = (query_order, create_support_ticket)


def _resolve_model_for_summarization(model: str | BaseChatModel) -> BaseChatModel:
    """Resolve a model string or instance to a BaseChatModel for summarization.

    Args:
        model: Either a provider:model string (e.g., "openai:gpt-4o-mini") or
            a BaseChatModel instance.

    Returns:
        A BaseChatModel instance suitable for use in SummarizationMiddleware.
        If model is already a BaseChatModel, returns it unchanged. If model is
        a string spec, resolves it via langchain's init_chat_model.
    """
    if isinstance(model, str):
        return init_chat_model(model)
    return model


def _default_context_middleware(model: str | BaseChatModel) -> list[Any]:
    """Build default context management middleware list.

    Returns middleware for:
    - Token-aware summarization (with trigger_tokens from settings)
    - Tool output truncation (with max_length from settings)

    Order: [summarization, limit-output] so both middleware can interact.

    Args:
        model: Chat model (string spec or BaseChatModel instance) used for
            summarization.

    Returns:
        A list of middleware instances ready for create_deep_agent(middleware=[...]).
    """
    resolved = _resolve_model_for_summarization(model)
    settings = get_settings()
    return [
        build_summarization_middleware(
            resolved,
            trigger=("tokens", settings.summarization_trigger_tokens),
            keep=("messages", settings.summarization_keep_messages),
        ),
        LimitToolOutputMiddleware(
            max_length=settings.tool_output_max_length,
        ),
    ]


def _default_research_subagent() -> Any:
    """Build default research subagent.

    Returns a research subagent that can be used for long lookups/gathering
    without polluting main agent context.

    Imports here to avoid circular imports between graph.py and subagents.py.

    Returns:
        A subagent spec dict suitable for create_deep_agent(subagents=[...]).
    """
    # Import here to avoid circular imports
    from src.agent.context.subagents import build_research_subagent

    return build_research_subagent()


def build_system_prompt(base: str | None = None) -> str:
    """Return the agent system prompt, appending long-term-memory guidance.

    Args:
        base: Optional deployment-specific opening instructions. When ``None``,
            only the memory guidance is used.

    Returns:
        ``base`` followed by the memory guidance (blank-line separated) so the
        agent both saves and recalls the user's long-term facts via
        ``/memory/notes.md``.
    """
    parts = [part for part in (base, MEMORY_GUIDANCE) if part]
    return "\n\n".join(parts)


def build_agent(
    *,
    model: str | BaseChatModel,
    store: BaseStore | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    system_prompt: str | None = None,
    skills: Sequence[str] = ("/skills/",),
    backend: BackendProtocol | None = None,
    tools: Sequence[BaseTool] = DEFAULT_TOOLS,
    context_schema: type[Any] = DEFAULT_CONTEXT_SCHEMA,
    enqueue: Callable[[str, str], None] | None = None,
    subagents: Sequence[Any] | None = None,
    middleware: Sequence[Any] = (),
    enable_default_context_management: bool = True,
) -> CompiledStateGraph:
    """Build a compiled deep agent wired with the vertex-agent backend.

    Args:
        model: Chat model — a ``provider:model`` string (real deployments) or a
            ``BaseChatModel`` instance (fake model in test/index). Required.
        store: LangGraph ``BaseStore`` for long-term (cross-session) memory.
            Required for the ``/memory/`` route to work; every graph bound to a
            store uses it via ``get_store()`` at call time.
        checkpointer: Optional checkpointer (``MemorySaver`` dev /
            ``PostgresSaver`` production, see ``src/memory/checkpointer``) for
            short-term per-session memory.
        system_prompt: Agent system prompt. Defaults to
            :func:`build_system_prompt` (memory guidance).
        skills: Skill source paths loaded at runtime, e.g. ``("/skills/",)``.
            Left empty to disable the skills middleware.
        backend: Filesystem backend. Defaults to the Store-backed memory
            filesystem (disk default + ``/memory/`` → Store).
        tools: Custom tools **added** to the built-in filesystem/task tools.
            Defaults to the Task 2 business tools (``query_order``,
            ``create_support_ticket``).
        context_schema: LangGraph context schema carrying ``user_id`` per
            invoke. Defaults to ``UserContext`` so that
            ``invoke(..., context=UserContext(user_id=...))`` gives each user a
            distinct ``("memories", user_id)`` namespace.
        enqueue: Optional end-of-turn hook for Phase 6 dreaming:
            ``enqueue(thread_id, user_id)`` is called (via an ``after_agent``
            middleware, enqueue-only) after every agent turn finishes. ``None``
            (default) wires no middleware — behaviour identical to Task 5.
        subagents: Optional sequence of subagents to inject into the compiled
            graph. When ``None`` (default), no subagents are added. Task B will
            implement automatic subagent initialization based on
            ``enable_default_context_management``.
        middleware: Optional sequence of custom middleware to inject into the
            compiled graph. Client-provided middleware will be ordered before
            any built-in middleware (enqueue, etc.). Defaults to empty.
        enable_default_context_management: Flag controlling whether default
            context management middleware (summarization, output limiting) is
            enabled. Defaults to ``True``. Used in Task B for actual context
            middleware wiring; has no effect in Task A.

    Returns:
        A compiled agent graph. Invoke with
        ``{"messages": [{"role": "user", "content": ...}]}`` and, for per-user
        memory namespaces, ``context=UserContext(user_id=...)``.
    """
    if system_prompt is None:
        system_prompt = build_system_prompt()
    if backend is None:
        backend = build_memory_filesystem()

    # Build subagents list: use default research subagent if not provided
    resolved_subagents = list(subagents) if subagents is not None else [
        _default_research_subagent()
    ]

    # Build middleware list: default context management comes first so caller can override
    built_middleware: list[Any] = []

    if enable_default_context_management:
        # Add default context middleware (summarization + output limiting) first
        built_middleware = _default_context_middleware(model)

    # Append caller's custom middleware
    built_middleware.extend(middleware)

    # Append enqueue middleware if provided
    if enqueue is not None:
        built_middleware.append(EnqueueAfterTurnMiddleware(enqueue))

    return create_deep_agent(
        model=model,
        tools=list(tools),
        system_prompt=system_prompt,
        skills=list(skills),
        backend=backend,
        checkpointer=checkpointer,
        store=store,
        context_schema=context_schema,
        subagents=resolved_subagents or None,
        middleware=built_middleware or None,
    )


__all__ = [
    "DEFAULT_CONTEXT_SCHEMA",
    "DEFAULT_TOOLS",
    "MEMORY_GUIDANCE",
    "build_agent",
    "build_system_prompt",
]