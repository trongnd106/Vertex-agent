"""Phase 6: Dreaming / self-improvement — separate dream graph, enqueue hook, consolidation.

Discovery recorded here (see the task-6 report for the full evidence):

- **LangMem reflection**: installed `langmem` **has** `ReflectionExecutor`
  (`langmem/reflection.py`, both `RemoteReflectionExecutor` and
  `LocalReflectionExecutor`). Verdict: NOT used. The local form spawns a
  non-daemon background-worker thread in `__init__` and delegates the whole
  write to a LangMem `reflection` runnable that owns its own memory schema /
  writes — it cannot drive our `DreamOutput` (facts/lessons/conflicts split),
  our `("memories", user_id)` vs `("system", "lessons")` namespace separation,
  or the S8 conflict no-overwrite rule, and it is non-deterministic for tests.
  We therefore write our own dream graph per the plan design.
- **`checkpointer.get_tuple(config)`** exists on both `MemorySaver` and
  `PostgresSaver` (probing). deepagents keeps `messages` on a `DeltaChannel`
  (`deepagents/graph.py:73`), so messages are NOT in the tuple's
  `channel_values`; reconstruction uses langgraph's own ancestor-walk API
  (`BaseCheckpointSaver.get_delta_channel_history`,
  `langgraph/checkpoint/base/__init__.py:582`, + `channels_from_checkpoint`,
  `langgraph/pregel/_checkpoint.py:229`) which is exactly what
  `Pregel.get_state` uses. Verified to reproduce `get_state().values["messages"]`.
- **Middleware hooks**: `langchain.agents.middleware.AgentMiddleware` (the base
  deepagents' middleware subclass) exposes `after_agent` / `after_model` /
  `before_agent` / `before_model` (+ async) at
  `langchain/agents/middleware/types.py` (`after_agent` at :266). Hooks are
  registered as real LangGraph nodes (`langchain/agents/factory.py:1624-1645`)
  so `get_config()` (thread_id) and `runtime.context.user_id` are available —
  live-probed. No `on_tool_end` (discovery §12.9).
- **Store Item timestamps**: `langgraph.store.base.Item` exposes only
  `(value, key, namespace, created_at, updated_at)` — **no read/access
  tracking**. `updated_at` bumps on `put` only (live-probed on PostgresStore).
  Consolidation therefore lowers priority on the best available signal —
  `updated_at` (last write) — documented honestly; reads are untracked.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.store.memory import InMemoryStore

from src.agent.graph import build_agent, build_memory_filesystem  # noqa: F401
from src.memory.checkpointer import get_checkpointer
from src.memory.memory_backend import UserContext
from src.memory.dreaming.consolidate import (
    MemoryRecord,
    plan_consolidation,
    run_consolidation,
)
from src.memory.dreaming.dream import (
    CONFLICT_MARKERS_NAMESPACE,
    LESSONS_NAMESPACE,
    DreamOutput,
    build_dream_agent,
    memories_namespace,
    write_dream_results,
)
from src.memory.dreaming.enqueue import EnqueueAfterTurnMiddleware
from src.memory.dreaming.loader import load_thread_messages, scan_thread_ids
from src.memory.store import get_store
from tests.fake_model import ScriptedChatModel, StructuredScriptedModel


POSTGRES_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://deepagents:deepagents@localhost:5432/deepagents"
)


def _postgres_reachable() -> bool:
    try:
        with psycopg.connect(POSTGRES_URL, connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        return True
    except Exception:
        return False


POSTGRES_AVAILABLE = _postgres_reachable()
skip_postgres = pytest.mark.skipif(
    not POSTGRES_AVAILABLE, reason="Postgres not reachable (set TEST_DATABASE_URL)"
)


# --------------------------------------------------------------------------- #
# 1) History loader: real prior session reconstructed from a MemorySaver      #
# --------------------------------------------------------------------------- #
def _run_main_session(checkpointer, store, thread_id, user_id="u1"):
    model = ScriptedChatModel(script=[AIMessage(content="r1"), AIMessage(content="r2")])
    agent = build_agent(model=model, store=store, checkpointer=checkpointer)
    cfg = {"configurable": {"thread_id": thread_id}}
    agent.invoke({"messages": [{"role": "user", "content": "q1"}]}, config=cfg, context=UserContext(user_id=user_id))
    agent.invoke({"messages": [{"role": "user", "content": "q2"}]}, config=cfg, context=UserContext(user_id=user_id))
    return agent


def test_history_loader_reconstructs_full_session_messages():
    saver = MemorySaver()
    agent = _run_main_session(saver, get_store(), "dream-hist")
    # Use get_state path (handles deepagents reducer-based message storage)
    msgs = load_thread_messages(saver, "dream-hist", get_state=agent.get_state)
    assert [m.content for m in msgs] == ["q1", "r1", "q2", "r2"]
    assert all(m.id for m in msgs)


def test_history_loader_unknown_thread_is_empty():
    assert load_thread_messages(MemorySaver(), "never-existed") == []


# --------------------------------------------------------------------------- #
# 2) Dream graph end-to-end: structured output -> facts/lessons/conflicts     #
# --------------------------------------------------------------------------- #
def test_dream_graph_writes_facts_and_lessons_into_separate_namespaces():
    saver = MemorySaver()
    store = get_store()
    agent = _run_main_session(saver, store, "dream-e2e")

    dream_result = DreamOutput(
        facts=["User prefers Vietnamese replies", "User's order #123 was refunded"],
        lessons=["query_order tool should quote the total in the first line"],
        conflicts=[],
    )
    model = StructuredScriptedModel(structured=[dream_result])
    dream = build_dream_agent(model=model, store=store, checkpointer=saver, get_state=agent.get_state)

    state = dream.invoke({"thread_id": "dream-e2e", "user_id": "u1"})

    assert state["facts"] == dream_result.facts
    assert state["lessons"] == dream_result.lessons
    assert state["conflicts"] == []

    facts = list(store.search(memories_namespace("u1")).items)
    lessons = list(store.search(LESSONS_NAMESPACE).items)
    assert sorted([it.value["content"] for it in facts]) == sorted(dream_result.facts)
    assert sorted([it.value["content"] for it in lessons]) == sorted(dream_result.lessons)

    memory_keys = {it.key for it in facts}
    lesson_keys = {it.key for it in lessons}
    assert memory_keys.isdisjoint(lesson_keys)
    assert all(it.namespace == memories_namespace("u1") for it in facts)
    assert all(it.namespace == LESSONS_NAMESPACE for it in lessons)

    assert list(store.search(CONFLICT_MARKERS_NAMESPACE).items) == []


def test_dream_graph_no_history_reports_error_and_writes_nothing():
    saver = MemorySaver()
    store = get_store()
    model = StructuredScriptedModel(structured=[DreamOutput(facts=["x"])])
    dream = build_dream_agent(model=model, store=store, checkpointer=saver)
    state = dream.invoke({"thread_id": "no-history", "user_id": "u1"})
    assert "error" in state
    assert store.search(memories_namespace("u1")).items == []
    assert store.search(LESSONS_NAMESPACE).items == []


def test_write_dream_results_is_idempotent_same_key():
    store = InMemoryStore()
    w1 = write_dream_results(store, user_id="u1", thread_id="t1",
                             facts=["same fact"], lessons=[], conflicts=[])
    w2 = write_dream_results(store, user_id="u1", thread_id="t1",
                             facts=["same fact"], lessons=[], conflicts=[])
    assert w1.facts == w2.facts == 1
    assert len(store.search(memories_namespace("u1"))) == 1


# --------------------------------------------------------------------------- #
# 3) S8: conflicts recorded as markers, existing memory NOT overwritten       #
# --------------------------------------------------------------------------- #
def test_conflict_does_not_overwrite_existing_memory_and_records_marker():
    saver = MemorySaver()
    store = InMemoryStore()
    agent = _run_main_session(saver, store, "dream-conf")

    store.put(memories_namespace("u1"), "fact-preexisting",
              {"kind": "fact", "content": "User prefers Vietnamese", "priority": 3})

    dream_result = DreamOutput(
        facts=[],
        lessons=[],
        conflicts=["User says preferred language is Vietnamese but later says English"],
    )
    dream = build_dream_agent(
        model=StructuredScriptedModel(structured=[dream_result]),
        store=store,
        checkpointer=saver,
        get_state=agent.get_state,
    )
    state = dream.invoke({"thread_id": "dream-conf", "user_id": "u1"})

    assert state["conflicts"] == dream_result.conflicts

    existing = store.get(memories_namespace("u1"), "fact-preexisting")
    assert existing is not None
    assert existing.value["content"] == "User prefers Vietnamese"

    markers = store.search(CONFLICT_MARKERS_NAMESPACE)
    assert len(markers) == 1
    assert markers[0].value["conflict"] == dream_result.conflicts[0]
    assert markers[0].value["user_id"] == "u1"
    assert markers[0].value["thread_id"] == "dream-conf"


# --------------------------------------------------------------------------- #
# 4) Enqueue hook: enqueues thread_id at end-of-turn, never dreams            #
# --------------------------------------------------------------------------- #
def test_enqueue_after_turn_middleware_enqueues_without_processing():
    saver = MemorySaver()
    store = InMemoryStore()
    enqueued: list[tuple[str, str]] = []
    agent = build_agent(
        model=ScriptedChatModel(script=[AIMessage(content="bye")]),
        store=store,
        checkpointer=saver,
        enqueue=lambda tid, uid: enqueued.append((tid, uid)),
    )
    agent.invoke(
        {"messages": [{"role": "user", "content": "hi"}]},
        config={"configurable": {"thread_id": "enq-t"}},
        context=UserContext(user_id="u9"),
    )
    assert enqueued == [("enq-t", "u9")]
    # Only enqueued: nothing dreamed into the store.
    assert list(store.search(memories_namespace("u9"))) == []
    assert list(store.search(LESSONS_NAMESPACE)) == []


def test_enqueue_middleware_skips_without_user_context():
    enqueued: list[tuple[str, str]] = []
    agent = build_agent(
        model=ScriptedChatModel(script=[AIMessage(content="hi")]),
        checkpointer=MemorySaver(),
        enqueue=lambda tid, uid: enqueued.append((tid, uid)),
    )
    agent.invoke(
        {"messages": [{"role": "user", "content": "x"}]},
        config={"configurable": {"thread_id": "enq-nocxt"}},
        # No context=... -> runtime.context is None -> nothing to enqueue.
    )
    assert enqueued == []


# --------------------------------------------------------------------------- #
# 5) Consolidate: duplicates merged + stale memory de-prioritized             #
# --------------------------------------------------------------------------- #
def _rec(key, content, created, updated, priority=3):
    return MemoryRecord(
        key=key,
        value={"kind": "fact", "content": content, "priority": priority},
        created_at=created,
        updated_at=updated,
    )


def test_consolidate_plan_merges_duplicates_and_deprioritizes_stale():
    now = datetime.now(timezone.utc)
    new = now - timedelta(days=1)
    stale = now - timedelta(days=60)

    records = [
        _rec("fact-a", "User likes Coffee", new, stale),      # stale duplicate -> merged away
        _rec("fact-b", "user   likes  coffee", stale, new),   # newest duplicate -> keeper, fresh
        _rec("fact-c", "User prefers Tea", new, new),         # fresh unique -> untouched
        _rec("fact-d", "User is in Hanoi", new, stale),       # stale unique -> deprioritized
    ]
    plan = plan_consolidation(records, stale_after_days=30, now=now)

    assert plan.merges == (("fact-b", ("fact-a",)),)
    assert plan.delete_keys == ["fact-a"]
    by_key = {u.key: u.fields for u in plan.updates}
    assert by_key["fact-d"] == {"priority": 2, "lowered_at": now.isoformat()}
    assert "fact-b" not in by_key      # keeper is fresh -> untouched
    assert "fact-c" not in by_key


def test_consolidate_stale_low_priority_marks_retracted_never_deletes():
    now = datetime.now(timezone.utc)
    stale = now - timedelta(days=60)
    records = [
        _rec("fact-low", "aging fact", stale, stale, priority=1),
    ]
    plan = plan_consolidation(records, stale_after_days=30, now=now)
    assert plan.merges == ()
    by_key = {u.key: u.fields for u in plan.updates}
    # Priority floor: item is flagged retracted, never deleted.
    assert by_key["fact-low"]["retracted"] is True
    assert by_key["fact-low"]["priority"] <= 1


def test_consolidate_store_run_is_idempotent():
    store = InMemoryStore()
    ns = ("memories", "u1")
    now = datetime.now(timezone.utc)
    store.put(ns, "fact-a", {"kind": "fact", "content": "Coffee", "priority": 3})
    store.put(ns, "fact-b", {"kind": "fact", "content": "coffee", "priority": 3})
    store.put(ns, "fact-fresh", {"kind": "fact", "content": "Hanoi", "priority": 3})

    r1 = run_consolidation(store, ns, stale_after_days=30, now=now)
    assert r1.merged_keys == ["fact-b"]          # newest duplicate wins
    entries = {it.key: it.value for it in store.search(ns)}
    assert "fact-a" not in entries
    assert entries["fact-b"]["content"] == "coffee"
    assert r1.deprioritized_keys == []           # all fresh at `now`

    future = now + timedelta(days=100)
    r2 = run_consolidation(store, ns, stale_after_days=30, now=future)
    assert sorted(r2.deprioritized_keys) == ["fact-b", "fact-fresh"]
    entries = {it.key: it.value for it in store.search(ns)}
    assert entries["fact-b"]["priority"] == 2
    assert entries["fact-b"]["lowered_at"]
    assert entries["fact-fresh"]["priority"] == 2

    r3 = run_consolidation(store, ns, stale_after_days=30, now=future)
    assert r3.merged_keys == []
    assert r3.deprioritized_keys == []           # idempotent: already lowered in-window


# --------------------------------------------------------------------------- #
# 6) Cold-scan: enumerate distinct thread_ids from the checkpointer           #
# --------------------------------------------------------------------------- #
def test_scan_thread_ids_lists_distinct_threads():
    saver = MemorySaver()
    for tid in ("scan-1", "scan-2"):
        _run_main_session(saver, get_store(), tid)
    ids = scan_thread_ids(saver)
    assert sorted(ids) == ["scan-1", "scan-2"]


# --------------------------------------------------------------------------- #
# 7) Postgres: dream write path + consolidation (run for real, DB is up)      #
# --------------------------------------------------------------------------- #
@skip_postgres
def test_dream_graph_postgres_store_and_saver():
    thread_id = f"pg-dream-{uuid.uuid4().hex[:8]}"
    store = get_store(POSTGRES_URL)
    saver = get_checkpointer(POSTGRES_URL)
    try:
        _run_main_session(saver, store, thread_id, user_id="pg-u1")
        dream_result = DreamOutput(
            facts=["PG fact about user"],
            lessons=["PG lesson about tools"],
            conflicts=[],
        )
        dream = build_dream_agent(
            model=StructuredScriptedModel(structured=[dream_result]),
            store=store,
            checkpointer=saver,
        )
        state = dream.invoke({"thread_id": thread_id, "user_id": "pg-u1"})
        assert state["facts"] == ["PG fact about user"]
        facts = list(store.search(memories_namespace("pg-u1")))
        lessons = list(store.search(LESSONS_NAMESPACE).items)
        assert any(it.value["content"] == "PG fact about user" for it in facts)
        assert any(it.value["content"] == "PG lesson about tools" for it in lessons)
    finally:
        try:
            saver.delete_thread(thread_id)
        except Exception:
            pass
        saver.conn.close()
        store.conn.close()


def _age_postgres_items(conn, namespace, ages):
    """Backdate `updated_at` on store rows (prefix is dot-joined namespace)."""
    prefix = ".".join(namespace)
    with conn.cursor() as cur:
        for key, days in ages.items():
            cur.execute(
                "UPDATE store SET updated_at = now() - (%s * interval '1 day') "
                "WHERE key = %s AND prefix = %s",
                (days, key, prefix),
            )
    conn.commit()


@skip_postgres
def test_consolidate_postgres_store():
    store = get_store(POSTGRES_URL)
    now = datetime.now(timezone.utc)
    try:
        ns = ("memories", "pg-consolidate-u1")
        for k, v in (
            ("fact-a", {"kind": "fact", "content": "Same", "priority": 3}),
            ("fact-b", {"kind": "fact", "content": "same", "priority": 3}),
            ("fact-stale", {"kind": "fact", "content": "User prefers Tea", "priority": 3}),
            ("fact-fresh", {"kind": "fact", "content": "User is in Hanoi", "priority": 3}),
        ):
            store.put(ns, k, v)
        _age_postgres_items(store.conn, ns, {"fact-a": 60, "fact-stale": 60})

        r = run_consolidation(store, ns, stale_after_days=30, now=now)
        assert r.merged_keys == ["fact-b"]
        assert r.deleted_keys == ["fact-a"]
        assert r.deprioritized_keys == ["fact-stale"]
        entries = {it.key: it.value for it in store.search(ns)}
        assert "fact-a" not in entries
        assert entries["fact-b"]["content"] == "same"
        assert entries["fact-stale"]["priority"] == 2
        assert entries["fact-stale"]["lowered_at"]
        assert entries["fact-fresh"]["priority"] == 3
    finally:
        for it in store.search(ns):
            store.delete(ns, it.key)
        store.conn.close()