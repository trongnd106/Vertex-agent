"""Phase 4: session memory via a LangGraph checkpointer.

Two backends prove the plan's core claim that the checkpointer auto-persists
the full graph state per ``thread_id`` and that resume is just invoking with
the same ``thread_id``:

- ``MemorySaver`` (dev/test; Ruling M3) proves multi-turn continuity, fresh-graph
  (simulated process restart) resume, and virtual-FS persistence across turns.
- ``PostgresSaver`` (production) proves *true* cross-process persistence and
  drives the stale-thread cleanup job. These tests are skippable when the DB is
  unreachable (Ruling M3) and are executed when the compose Postgres is up.
"""

from __future__ import annotations

import datetime as _dt
import os
import uuid

import psycopg
import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from deepagents import create_deep_agent
from deepagents.backends.state import StateBackend

from src.memory.checkpointer import get_checkpointer
from src.memory.cleanup import cleanup_stale_threads
from tests.fake_model import ScriptedChatModel

from langgraph.checkpoint.postgres import PostgresSaver

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


def _human_texts(messages) -> list[str]:
    return [m.content for m in messages if m.type == "human" and not str(m.content).startswith("<system-reminder>")]


class ContinuityModel(ScriptedChatModel):
    """Replies reporting how many human turns it can see in the restored state."""

    def _next_message(self) -> AIMessage:
        humans = _human_texts(self.last_messages)
        what = humans[-1] if humans else None
        return AIMessage(content=f"saw={len(humans)} last={what!r}")


# --------------------------------------------------------------------------- #
# 1) Multi-turn continuity (MemorySaver)                                      #
# --------------------------------------------------------------------------- #
def test_memory_saver_multi_turn_continuity():
    saver = MemorySaver()
    model = ContinuityModel()
    agent = create_deep_agent(model=model, checkpointer=saver)
    cfg = {"configurable": {"thread_id": "thread-A"}}

    first = agent.invoke({"messages": [{"role": "user", "content": "m1"}]}, config=cfg)
    assert first["messages"][-1].content == "saw=1 last='m1'"

    second = agent.invoke({"messages": [{"role": "user", "content": "m2"}]}, config=cfg)
    assert second["messages"][-1].content == "saw=2 last='m2'"
    # Full history present in the restored state (both turns).
    assert _human_texts(second["messages"]) == ["m1", "m2"]


# --------------------------------------------------------------------------- #
# 2) Fresh graph over the SAME saver resumes (simulated process restart)      #
# --------------------------------------------------------------------------- #
def test_fresh_graph_resumes_same_thread_on_same_saver():
    saver = MemorySaver()
    cfg = {"configurable": {"thread_id": "thread-B"}}

    graph_1 = create_deep_agent(model=ContinuityModel(), checkpointer=saver)
    graph_1.invoke({"messages": [{"role": "user", "content": "turn1"}]}, config=cfg)

    # "Restart": a brand-new graph over the same saver resumes thread-B.
    graph_2 = create_deep_agent(model=ContinuityModel(), checkpointer=saver)
    resumed = graph_2.invoke(
        {"messages": [{"role": "user", "content": "turn2"}]}, config=cfg
    )
    assert _human_texts(resumed["messages"]) == ["turn1", "turn2"]
    assert resumed["messages"][-1].content == "saw=2 last='turn2'"


# --------------------------------------------------------------------------- #
# 3) Virtual-FS persistence across turns (state, not just messages)           #
# --------------------------------------------------------------------------- #
class FsMemoryModel(ScriptedChatModel):
    """Writes a file to the virtual FS in turn 1, reads it back in turn 2."""

    def __init__(self):
        super().__init__()
        self._step = 0

    def _next_message(self) -> AIMessage:
        self._step += 1
        if self._step == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "write_file",
                        "args": {"file_path": "/mem/note.txt", "content": "MEM-CONTENT-42"},
                        "id": "c1",
                        "type": "tool_call",
                    }
                ],
            )
        if self._step == 2:
            return AIMessage(content="DONE-WRITE")  # end turn 1
        if self._step == 3:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "read_file",
                        "args": {"file_path": "/mem/note.txt"},
                        "id": "c2",
                        "type": "tool_call",
                    }
                ],
            )
        for m in reversed(self.last_messages):
            if m.type == "tool":
                return AIMessage(content="READ:" + str(m.content))
        return AIMessage(content="no tool result")


def test_virtual_fs_persists_across_turns():
    saver = MemorySaver()
    model = FsMemoryModel()
    agent = create_deep_agent(model=model, backend=StateBackend(), checkpointer=saver)
    cfg = {"configurable": {"thread_id": "thread-FS"}}

    turn1 = agent.invoke({"messages": [{"role": "user", "content": "write"}]}, config=cfg)
    assert turn1["messages"][-1].content == "DONE-WRITE"

    turn2 = agent.invoke({"messages": [{"role": "user", "content": "read"}]}, config=cfg)
    last = turn2["messages"][-1].content
    assert "READ:" in last
    assert "MEM-CONTENT-42" in last, f"read-back did not contain content: {last!r}"


# --------------------------------------------------------------------------- #
# 4) get_checkpointer factory (no DB -> MemorySaver)                          #
# --------------------------------------------------------------------------- #
def test_get_checkpointer_defaults_to_memory_saver(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    cp = get_checkpointer()
    assert isinstance(cp, MemorySaver)


# --------------------------------------------------------------------------- #
# 5) Postgres: true cross-process persistence (skippable)                     #
# --------------------------------------------------------------------------- #
@skip_postgres
def test_postgres_cross_process_persistence():
    thread_id = f"pg-{uuid.uuid4().hex[:8]}"
    cfg = {"configurable": {"thread_id": thread_id}}

    def _saver():
        return get_checkpointer(POSTGRES_URL)

    saver_1 = _saver()
    saver_2 = _saver()
    try:
        graph_1 = create_deep_agent(model=ContinuityModel(), checkpointer=saver_1)
        graph_1.invoke({"messages": [{"role": "user", "content": "p1"}]}, config=cfg)

        # A brand-new saver + graph (real process restart) resumes the thread.
        graph_2 = create_deep_agent(model=ContinuityModel(), checkpointer=saver_2)
        resumed = graph_2.invoke(
            {"messages": [{"role": "user", "content": "p2"}]}, config=cfg
        )
        assert _human_texts(resumed["messages"]) == ["p1", "p2"]
        assert resumed["messages"][-1].content == "saw=2 last='p2'"
    finally:
        saver_1.conn.close()
        saver_2.conn.close()
        # Self-cleanup: a fresh saver deletes this test's thread.
        saver = _saver()
        try:
            saver.delete_thread(thread_id)
        finally:
            saver.conn.close()


# --------------------------------------------------------------------------- #
# 6) Stale-thread cleanup job (skippable)                                     #
# --------------------------------------------------------------------------- #
def _insert_old_thread(conn: psycopg.Connection, thread_id: str, age_days: int) -> None:
    ts = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=age_days)).isoformat()
    cid = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO checkpoints "
            "(thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, "
            " checkpoint, metadata) VALUES (%s, '', %s, NULL, NULL, %s, '{}'::jsonb)",
            (thread_id, cid, f'{{"ts":"{ts}"}}'),
        )


@skip_postgres
def test_cleanup_deletes_only_stale_threads():
    stale = f"stale-{uuid.uuid4().hex[:6]}"
    fresh = f"fresh-{uuid.uuid4().hex[:6]}"
    cfg = {"configurable": {"thread_id": fresh}}

    saver = get_checkpointer(POSTGRES_URL)
    conn = saver.conn
    try:
        # A real fresh thread (recent last activity).
        create_deep_agent(model=ContinuityModel(), checkpointer=saver).invoke(
            {"messages": [{"role": "user", "content": "keep"}]}, config=cfg
        )
        # A manual stale thread whose last checkpoint is 90 days old.
        _insert_old_thread(conn, stale, age_days=90)

        stale_ids = cleanup_stale_threads(
            conn, max_age_days=30, dry_run=True, checkpointer=saver
        )
        assert stale in stale_ids
        assert fresh not in stale_ids

        deleted = cleanup_stale_threads(
            conn, max_age_days=30, dry_run=False, checkpointer=saver
        )
        assert deleted == [stale]

        # Stale thread is gone from the DB; fresh thread still has history.
        with conn.cursor() as cur:
            cur.execute("SELECT thread_id FROM checkpoints WHERE thread_id = %s", (stale,))
            assert cur.fetchone() is None

        saver2 = get_checkpointer(POSTGRES_URL)
        try:
            resumed = create_deep_agent(model=ContinuityModel(), checkpointer=saver2).invoke(
                {"messages": [{"role": "user", "content": "again"}]}, config=cfg
            )
            assert _human_texts(resumed["messages"]) == ["keep", "again"]
        finally:
            saver2.conn.close()

        # Negative control: a DELETED thread_id no longer resumes — re-invoking
        # the stale thread from a fresh graph over a fresh saver (no in-memory
        # state can leak) must see NO prior history: saw=1, not saw=2.
        saver3 = get_checkpointer(POSTGRES_URL)
        try:
            reborn = create_deep_agent(model=ContinuityModel(), checkpointer=saver3).invoke(
                {"messages": [{"role": "user", "content": "hello-again"}]},
                config={"configurable": {"thread_id": stale}},
            )
            assert reborn["messages"][-1].content == "saw=1 last='hello-again'"
            assert _human_texts(reborn["messages"]) == ["hello-again"]
        finally:
            saver3.conn.close()
    finally:
        for tid in (stale, fresh):
            try:
                saver.delete_thread(tid)
            except Exception:
                pass
        conn.close()


@skip_postgres
def test_cleanup_factory_builds_ready_saver():
    saver = get_checkpointer(POSTGRES_URL)
    try:
        assert isinstance(saver, PostgresSaver)
        assert saver.conn is not None
    finally:
        saver.conn.close()
