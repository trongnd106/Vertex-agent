"""Phase 6 — Dreaming / self-improvement.

A separate, standalone LangGraph graph ("the dream") reads finished-session
histories out of the checkpointer, extracts structured insights with a cheap
model via the same `response_format`/`with_structured_output` mechanism the
main agent uses, and writes them to the Store under cleanly separated
namespaces — user facts in ``("memories", <user_id>)``, agent lessons in
``("system", "lessons")``, conflicts as fail-safe markers in
``("system", "conflict_markers")`` (never overwriting existing memories).

End-of-turn triggering is a non-blocking enqueue-only middleware hook
(`EnqueueAfterTurnMiddleware`); processing happens via the cold-scan
entrypoint (`python -m src.memory.dreaming.scan`) or a production queue
consumer. Periodic consolidation (`python -m src.memory.dreaming.consolidate`)
merges duplicates and de-prioritizes stale memories.
"""

from src.memory.dreaming.consolidate import (
    ConsolidationPlan,
    ConsolidationResult,
    ItemUpdate,
    MemoryRecord,
    plan_consolidation,
    run_consolidation,
)
from src.memory.dreaming.dream import (
    CONFLICT_MARKERS_NAMESPACE,
    DREAM_PROMPT,
    LESSONS_NAMESPACE,
    DreamOutput,
    DreamState,
    DreamWriteSummary,
    build_dream_agent,
    extract_dream,
    memories_namespace,
    write_dream_results,
)
from src.memory.dreaming.enqueue import (
    EnqueueAfterTurnMiddleware,
    make_enqueue_callback,
)
from src.memory.dreaming.loader import load_thread_messages, scan_thread_ids
from src.memory.dreaming.scan import dream_thread, scan_and_dream

__all__ = [
    "CONFLICT_MARKERS_NAMESPACE",
    "ConsolidationPlan",
    "ConsolidationResult",
    "DREAM_PROMPT",
    "DreamOutput",
    "DreamState",
    "DreamWriteSummary",
    "EnqueueAfterTurnMiddleware",
    "ItemUpdate",
    "LESSONS_NAMESPACE",
    "MemoryRecord",
    "build_dream_agent",
    "dream_thread",
    "extract_dream",
    "load_thread_messages",
    "make_enqueue_callback",
    "memories_namespace",
    "plan_consolidation",
    "run_consolidation",
    "scan_and_dream",
    "scan_thread_ids",
    "write_dream_results",
]