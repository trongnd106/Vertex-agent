"""Dreaming: a SEPARATE self-improvement graph, independent of the main agent.

Phase 6 runs a second, standalone LangGraph graph *beside* the main agent. It
reads a finished thread's history back from the checkpointer, asks a cheap
model for structured ``DreamOutput`` (user facts / agent lessons / conflicts)
through the exact `response_format` machinery the main agent supports
(`BaseChatModel.with_structured_output`), and writes the result into distinct
Store namespaces:

- ``facts``     → ``("memories", <user_id>)``    (same namespace as Task 5)
- ``lessons``   → ``("system", "lessons")``      (agent behavior, NOT user data)
- ``conflicts`` → ``("system", "conflict_markers")`` — recorded as markers
  and **never** written into the user's memories namespace, so an existing
  memory is never overwritten by a detected contradiction (S8 fail-safe).

LangMem check (recorded in the task report): installed `langmem` *does* ship
`ReflectionExecutor` (`langmem/reflection.py`), but its local form spawns a
non-daemon background worker thread and hands the entire write to a LangMem
memory-manager runnable — it cannot produce our `DreamOutput` schema, enforce
the memories/lessons namespace split, or apply the S8 conflict no-overwrite
rule, and it is non-deterministic for tests. This module therefore implements
the plan's own dream graph.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha1
from typing import Any, TypedDict

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, SystemMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph, StateGraph
from langgraph.store.base import BaseStore
from pydantic import BaseModel, Field

from src.memory.dreaming.loader import load_thread_messages

#: Per-user long-term memory namespace — the SAME tuple Task 5's
#: ``StoreBackend`` uses, so dream-extracted facts share the user's memory.
def memories_namespace(user_id: str) -> tuple[str, ...]:
    return ("memories", user_id)


#: Agent-behavior lessons live apart from user facts (plan S8 / Phase 6 step 3).
LESSONS_NAMESPACE: tuple[str, ...] = ("system", "lessons")

#: Conflict fail-safe markers (never merged into the memories namespace).
CONFLICT_MARKERS_NAMESPACE: tuple[str, ...] = ("system", "conflict_markers")


class DreamOutput(BaseModel):
    """Structured extraction produced by the dreaming graph.

    Routed through `response_format` / `with_structured_output` — never
    hand-parsed from JSON by us.
    """

    facts: list[str] = Field(default_factory=list)
    lessons: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)


class DreamState(TypedDict, total=False):
    thread_id: str
    user_id: str
    facts: list[str]
    lessons: list[str]
    conflicts: list[str]
    error: str


@dataclass(frozen=True)
class DreamWriteSummary:
    """What a single dream run wrote (counts over distinct normalized items)."""

    facts: int = 0
    lessons: int = 0
    conflicts: int = 0


DREAM_PROMPT = (
    "You are the self-improvement engine for a customer-support agent. Review "
    "the conversation transcript below and extract three kinds of insight.\n"
    "1. facts: durable, verifiable facts and preferences about the USER — names, "
    "preferences, constraints, account/order details. Never include how the "
    "agent behaved.\n"
    "2. lessons: what the agent should do differently next time — tool-usage "
    "lessons, error patterns, response-quality improvements. Never user facts.\n"
    "3. conflicts: pairs of user statements in this transcript that contradict "
    "each other and could make the agent contradict itself later.\n"
    "Return ONLY the structured schema requested; keep every insight to one "
    "concise sentence."
)

#: Stored-value keys used on memory items written by the dream.
PRIORITY_FIELD = "priority"
PRIORITY_DEFAULT = 3


def dream_key(kind: str, text: str) -> str:
    """Deterministic Store key for an insight, so re-dreaming is idempotent.

    Same normalized text on the same thread -> same key -> ``put`` overwrites
    in place instead of accumulating duplicates.
    """
    digest = sha1(text.encode("utf-8")).hexdigest()[:16]
    return f"{kind}-{digest}"


def extract_dream(messages: list[BaseMessage], model: BaseChatModel) -> DreamOutput:
    """Run the extraction model over a transcript (structured-output mechanism).

    `model.with_structured_output(DreamOutput)` is the model-level primitive
    that `create_agent`'s `response_format=` resolves to
    (`langchain_core/language_models/chat_models.py:2374`, and the strategy
    resolution in `langchain/agents/factory.py:1014-1022` / `:1355-1367`).
    Production passes a cheap real model; tests substitute a fake that
    implements `with_structured_output` deterministically.
    """
    runnable = model.with_structured_output(DreamOutput)
    result = runnable.invoke([SystemMessage(content=DREAM_PROMPT), *messages])
    if not isinstance(result, DreamOutput):
        result = DreamOutput.model_validate(result)
    return result


def write_dream_results(
    store: BaseStore,
    *,
    user_id: str,
    thread_id: str,
    facts: list[str],
    lessons: list[str],
    conflicts: list[str],
    now: datetime | None = None,
) -> DreamWriteSummary:
    """Persist a dream run into the Store, with cleanly separated namespaces.

    - Facts → ``("memories", user_id)`` (deduped by content-hash key).
    - Lessons → ``("system", "lessons")``.
    - Conflicts → ``("system", "conflict_markers")`` ONLY. A detected conflict
      never rewrites an existing user memory (S8): the conflicting statement is
      recorded as a marker, and no conflicting fact enters the memories
      namespace.

    Returns:
        A `DreamWriteSummary` with distinct-item counts.
    """
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    fact_ns = memories_namespace(user_id)
    seen_facts: set[str] = set()
    for fact in facts:
        content = fact.strip()
        if not content or content in seen_facts:
            continue
        seen_facts.add(content)
        store.put(
            fact_ns,
            dream_key("fact", content),
            {
                "kind": "fact",
                "content": content,
                PRIORITY_FIELD: PRIORITY_DEFAULT,
                "thread_id": thread_id,
                "dreamed_at": stamp,
            },
        )
    seen_lessons: set[str] = set()
    for lesson in lessons:
        content = lesson.strip()
        if not content or content in seen_lessons:
            continue
        seen_lessons.add(content)
        store.put(
            LESSONS_NAMESPACE,
            dream_key("lesson", content),
            {
                "kind": "lesson",
                "content": content,
                "thread_id": thread_id,
                "dreamed_at": stamp,
            },
        )
    seen_conflicts: set[str] = set()
    for conflict in conflicts:
        content = conflict.strip()
        if not content or content in seen_conflicts:
            continue
        seen_conflicts.add(content)
        store.put(
            CONFLICT_MARKERS_NAMESPACE,
            dream_key("conflict", content),
            {
                "kind": "conflict_marker",
                "conflict": content,
                "thread_id": thread_id,
                "user_id": user_id,
                "recorded_at": stamp,
            },
        )
    return DreamWriteSummary(
        facts=len(seen_facts),
        lessons=len(seen_lessons),
        conflicts=len(seen_conflicts),
    )


def _resolve_model(model: str | BaseChatModel) -> BaseChatModel:
    if isinstance(model, str):
        return init_chat_model(model)
    return model


def build_dream_agent(
    *,
    model: str | BaseChatModel,
    store: BaseStore,
    checkpointer: BaseCheckpointSaver,
    extractor: Any | None = None,
    get_state: Callable[[dict], Any] | None = None,
) -> CompiledStateGraph:
    """Build the standalone dreaming graph.

    The graph is deliberately separate from the main agent: it owns no tools,
    no filesystem, no middleware; it reads history from the checkpointer
    (closure), extracts `DreamOutput` via the structured-output mechanism, and
    writes to the Store. It is compiled WITHOUT its own checkpointer so
    invoking it never pollutes the main agent's thread history.

    Args:
        model: The (cheap) extraction model — a ``provider:model`` string or a
            ``BaseChatModel`` instance (fake in tests). Kept as an injectable
            param so production can pass e.g. ``"openai:gpt-4o-mini"`` and
            tests can pass a `StructuredScriptedModel`.
        store: The `BaseStore` (same instance/database the main agent uses).
        checkpointer: The checkpointer whose per-thread history to dream over.
        extractor: Optional override Runnable for `with_structured_output`
            (advanced/testing seam). Defaults to
            ``model.with_structured_output(DreamOutput)``.
        get_state: Optional ``agent.get_state(config)`` callable. When
            provided, ``load_thread_messages`` uses the agent's full state
            API to reconstruct messages (handles deepagents reducers).

    Returns:
        A compiled graph. Invoke with ``{"thread_id": ..., "user_id": ...}``.
    """
    chat_model = _resolve_model(model)
    if extractor is None:
        extractor = chat_model.with_structured_output(DreamOutput)

    def _extract(state: DreamState) -> dict[str, Any]:
        thread_id = state.get("thread_id")
        user_id = state.get("user_id")
        if not thread_id:
            return {"error": "thread_id is required", **state, "facts": [], "lessons": [], "conflicts": []}
        messages = load_thread_messages(checkpointer, thread_id, get_state=get_state)
        if not messages:
            return {
                "facts": [],
                "lessons": [],
                "conflicts": [],
                "error": f"no history for thread {thread_id!r}",
            }
        prompt = [SystemMessage(content=DREAM_PROMPT), *messages]
        result = extractor.invoke(prompt)
        if not isinstance(result, DreamOutput):
            result = DreamOutput.model_validate(result)
        return {
            "facts": list(result.facts),
            "lessons": list(result.lessons),
            "conflicts": list(result.conflicts),
        }

    def _write(state: DreamState) -> dict[str, Any]:
        user_id = state.get("user_id")
        thread_id = state.get("thread_id")
        if not user_id or not thread_id:
            return {"error": "user_id and thread_id are required to persist dreams"}
        summary = write_dream_results(
            store,
            user_id=user_id,
            thread_id=thread_id,
            facts=state.get("facts", []),
            lessons=state.get("lessons", []),
            conflicts=state.get("conflicts", []),
        )
        return {"wrote": summary}

    graph = StateGraph(DreamState)
    graph.add_node("extract", _extract)
    graph.add_node("persist", _write)
    graph.set_entry_point("extract")
    graph.add_edge("extract", "persist")
    graph.set_finish_point("persist")
    return graph.compile()


__all__ = [
    "CONFLICT_MARKERS_NAMESPACE",
    "DREAM_PROMPT",
    "DreamOutput",
    "DreamState",
    "DreamWriteSummary",
    "LESSONS_NAMESPACE",
    "build_dream_agent",
    "dream_key",
    "extract_dream",
    "memories_namespace",
    "write_dream_results",
]