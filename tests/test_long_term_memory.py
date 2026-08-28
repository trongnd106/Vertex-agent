"""Phase 5: long-term (cross-session) memory via the LangGraph Store.

Proves the plan's design authority (plan §4.5) against the *real* 0.7.9 wiring:

- The agent writes/reads long-term memory through the built-in filesystem
  tools on the Store-backed ``/memory/`` route (no custom memory tool needed).
- Two independent "sessions" (two fresh graphs) of the **same user** share one
  memory: session A writes a fact, a brand-new session B — same store, same
  ``UserContext(user_id=...)`` — reads it back (cross-thread/cross-session).
- Per-user namespaces ``("memories", user_id)`` really isolate users, because
  the live probe in Task 5 verified ``runtime.context.user_id`` flows from
  ``invoke(context=UserContext(user_id=...))`` into the namespace factory
  (``MULTI_USER = True``); there is no fabricated isolation here.
- Postgres production path (``PostgresStore`` over a fresh connection = a real
  process restart) and the checkpointer+store combination, skippable when the
  compose DB is unreachable (Ruling M3).
"""

from __future__ import annotations

import os
import uuid

import psycopg
import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

from src.agent.graph import build_agent
from src.memory.checkpointer import get_checkpointer
from src.memory.memory_backend import (
    MULTI_USER,
    USER_CONTEXT_SCHEMA,
    UserContext,
    build_memory_filesystem,
)
from src.memory.store import get_store
from tests.fake_model import ScriptedChatModel

POSTGRES_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://deepagents:deepagents@localhost:5432/deepagents"
)

FACT = "Alice prefers dark mode and speaks Vietnamese."


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


def _last_tool_content(model: ScriptedChatModel) -> str | None:
    for m in reversed(model.last_messages):
        if m.type == "tool":
            return str(m.content)
    return None


# --------------------------------------------------------------------------- #
# Fake models                                                                #
# --------------------------------------------------------------------------- #
class MemoryWriterModel(ScriptedChatModel):
    """Real write to /memory/notes.md via the built-in write_file tool."""

    def __init__(self, fact: str):
        super().__init__()
        self._fact = fact
        self._step = 0

    def _next_message(self) -> AIMessage:
        self._step += 1
        if self._step == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "write_file",
                        "args": {
                            "file_path": "/memory/notes.md",
                            "content": self._fact,
                        },
                        "id": "w1",
                        "type": "tool_call",
                    }
                ],
            )
        return AIMessage(content="WROTE")


class MemoryReaderModel(ScriptedChatModel):
    """Real read of /memory/notes.md via read_file, then echoes the result."""

    def _next_message(self) -> AIMessage:
        latest = _last_tool_content(self)
        if latest is None:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "read_file",
                        "args": {"file_path": "/memory/notes.md"},
                        "id": "r1",
                        "type": "tool_call",
                    }
                ],
            )
        return AIMessage(content="READ:" + latest)


class MemoryContinuityModel(ScriptedChatModel):
    """History-driven writer/reader used with a checkpointer+store (test (e)).

    Drives turn 1 (fact given, no write yet) to write the fact to
    /memory/notes.md; every subsequent turn (fact ``None``) only reads the
    notes and reports how many human turns the restored state contains. Being
    purely history-driven, a FRESH instance on a RESUMED thread keeps working:
    - no write_file result yet and a fact is given -> write the fact.
    - no read_file result yet -> read /memory/notes.md.
    - otherwise -> "saw=<n humans> READ:<last tool result>".
    """

    def __init__(self, fact: str | None = None):
        super().__init__()
        self._fact = fact

    @staticmethod
    def _has_tool(name: str, model: ScriptedChatModel) -> bool:
        return any(
            m.type == "tool" and getattr(m, "name", None) == name
            for m in model.last_messages
        )

    def _next_message(self) -> AIMessage:
        if not self._has_tool("write_file", self) and self._fact is not None:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "write_file",
                        "args": {
                            "file_path": "/memory/notes.md",
                            "content": self._fact,
                        },
                        "id": "cw1",
                        "type": "tool_call",
                    }
                ],
            )
        if not self._has_tool("read_file", self):
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "read_file",
                        "args": {"file_path": "/memory/notes.md"},
                        "id": "cr1",
                        "type": "tool_call",
                    }
                ],
            )
        humans = [
            m
            for m in self.last_messages
            if m.type == "human" and not str(m.content).startswith("<system-reminder>")
        ]
        return AIMessage(content=f"saw={len(humans)} READ:{_last_tool_content(self)}")


# --------------------------------------------------------------------------- #
# (a)+(b) cross-session retrieval + store-level assertion                     #
# --------------------------------------------------------------------------- #
def _invoke(agent, text: str, user_id: str, *, config=None):
    return agent.invoke(
        {"messages": [{"role": "user", "content": text}]},
        config=config,
        context=UserContext(user_id=user_id),
    )


def test_cross_session_same_user_retrieval_and_store_level():
    store = InMemoryStore()
    user = "alice"

    # Session A: a real fake-model turn that calls write_file on /memory/notes.md.
    session_a = build_agent(model=MemoryWriterModel(FACT), store=store)
    out_a = _invoke(session_a, "remember this", user)
    assert out_a["messages"][-1].content == "WROTE"

    # (b) Prove it really landed in the Store, under ("memories", user), NOT in
    # any thread/state.
    item = store.get(("memories", user), "/notes.md")
    assert item is not None, "fact must be stored in the Store namespace"
    assert FACT in item.value["content"]

    # Session B: a FRESH graph over the SAME store + SAME user ("new session").
    session_b = build_agent(model=MemoryReaderModel(), store=store)
    out_b = _invoke(session_b, "what do you know about me?", user)
    last = str(out_b["messages"][-1].content)
    assert "READ:" in last
    assert FACT in last, f"session B could not recall the fact: {last!r}"


# --------------------------------------------------------------------------- #
# (c) multi-user vs fixed mode                                                #
# --------------------------------------------------------------------------- #
def test_multi_user_namespaces_isolate_users():
    assert MULTI_USER is True, "probe shipped the context-schema multi-user mode"

    store = InMemoryStore()

    # u1 writes her fact into her own namespace.
    u1 = build_agent(model=MemoryWriterModel(FACT), store=store)
    _invoke(u1, "remember alice's pref", "user-1")
    assert store.get(("memories", "user-1"), "/notes.md") is not None
    assert store.get(("memories", "user-2"), "/notes.md") is None

    # u2 (fresh graph, same store) reads /memory/notes.md -> his own namespace
    # is empty; he must NOT see u1's memory.
    u2 = build_agent(model=MemoryReaderModel(), store=store)
    out_u2 = _invoke(u2, "what do you know about me?", "user-2")
    last2 = str(out_u2["messages"][-1].content)
    assert "not found" in last2.lower(), f"u2 should not see any memory: {last2!r}"
    assert FACT not in last2

    # And u1 still sees her own fact (u2's probe did not disturb her namespace).
    u1b = build_agent(model=MemoryReaderModel(), store=store)
    last1 = str(_invoke(u1b, "recall", "user-1")["messages"][-1].content)
    assert FACT in last1

    # What store.get sees, the backend sees: the namespaces differ per user.
    assert store.get(("memories", "user-1"), "/notes.md").value["content"] == FACT
    assert store.get(("memories", "user-2"), "/notes.md") is None


def test_multi_user_namespace_isolation_within_one_store_via_writes():
    """Both users write; each namespace keeps only its own notes."""
    store = InMemoryStore()
    u1 = build_agent(model=MemoryWriterModel("U1-FACT-A"), store=store)
    u2 = build_agent(model=MemoryWriterModel("U2-FACT-B"), store=store)
    _invoke(u1, "write fact A", "user-A")
    _invoke(u2, "write fact B", "user-B")

    assert store.get(("memories", "user-A"), "/notes.md").value["content"] == "U1-FACT-A"
    assert store.get(("memories", "user-B"), "/notes.md").value["content"] == "U2-FACT-B"

    # Cross-check via the backend, from a fresh third graph in each user's shoes.
    a = build_agent(model=MemoryReaderModel(), store=store)
    b = build_agent(model=MemoryReaderModel(), store=store)
    assert "U1-FACT-A" in str(_invoke(a, "mine", "user-A")["messages"][-1].content)
    assert "U1-FACT-A" not in str(_invoke(b, "mine", "user-B")["messages"][-1].content)
    assert "U2-FACT-B" in str(_invoke(b, "mine", "user-B")["messages"][-1].content)


def test_missing_user_context_raises_clear_error():
    """Honest guard: without context the per-user factory refuses, it doesn't
    silently write into a shared namespace."""
    store = InMemoryStore()
    agent = build_agent(model=MemoryWriterModel(FACT), store=store)
    with pytest.raises(RuntimeError, match="context=UserContext"):
        agent.invoke({"messages": [{"role": "user", "content": "remember"}]})


@skip_postgres
def test_get_store_postgres_ready_and_index_free():
    from langgraph.store.postgres import PostgresStore

    store = get_store(POSTGRES_URL)
    try:
        assert isinstance(store, PostgresStore)
        assert store.conn is not None
    finally:
        store.conn.close()


def test_memory_backend_routes_only_memory_route():
    """Skills stay on the disk default route; only /memory/ hits the Store."""
    from deepagents.backends.store import StoreBackend

    backend = build_memory_filesystem()
    routes = backend.routes
    assert set(routes) == {"/memory/"}
    assert isinstance(routes["/memory/"], StoreBackend)


# --------------------------------------------------------------------------- #
# (d) Postgres: true cross-process (fresh connection = fresh process)         #
# --------------------------------------------------------------------------- #
@skip_postgres
def test_postgres_cross_process_retrieval():
    user_id = f"pgmem-{uuid.uuid4().hex[:8]}"

    store_1 = get_store(POSTGRES_URL)
    store_2 = get_store(POSTGRES_URL)  # brand-new connection: real db round-trip
    try:
        # "Process 1": write a fact through graph bound to store_1.
        s1 = build_agent(model=MemoryWriterModel(FACT), store=store_1)
        _invoke(s1, "remember", user_id)

        # "Process 2": a fresh graph bound to a fresh store reads it back.
        item = store_2.get(("memories", user_id), "/notes.md")
        assert item is not None, "fresh PostgresStore must see the persisted fact"
        assert FACT in item.value["content"]

        s2 = build_agent(model=MemoryReaderModel(), store=store_2)
        last = str(_invoke(s2, "recall", user_id)["messages"][-1].content)
        assert FACT in last, f"cross-process recall failed: {last!r}"
    finally:
        for st in (store_1, store_2):
            try:
                st.delete(("memories", user_id), "/notes.md")
            except Exception:
                pass
            st.conn.close()


# --------------------------------------------------------------------------- #
# (e) checkpointer + store together                                           #
# --------------------------------------------------------------------------- #
def test_checkpointer_and_store_together_in_memory():
    user_id = "combined-carol"
    thread_1 = "thread-combined-1"
    thread_2 = "thread-combined-2"

    saver = MemorySaver()
    store = InMemoryStore()

    # Turn 1 (session 1 / thread 1): write the fact to long-term memory.
    g1 = build_agent(
        model=MemoryContinuityModel(FACT), store=store, checkpointer=saver
    )
    r1 = _invoke(
        g1, "remember this", user_id, config={"configurable": {"thread_id": thread_1}}
    )
    last1 = str(r1["messages"][-1].content)
    assert "saw=1" in last1, f"first session: {last1!r}"
    assert FACT in last1

    # Turn 2: SAME thread from a FRESH graph -> thread resume (saw=2) AND the
    # memory read (content comes from the Store).
    g2 = build_agent(
        model=MemoryContinuityModel(), store=store, checkpointer=saver
    )
    r2 = _invoke(
        g2, "and again", user_id, config={"configurable": {"thread_id": thread_1}}
    )
    last2 = str(r2["messages"][-1].content)
    assert "saw=2" in last2, f"checkpointer must resume the thread: {last2!r}"
    assert FACT in last2

    # Turn 3: a NEW thread (brand-new session), fresh graph -> no prior thread
    # history (saw=1) but the long-term memory is still recalled.
    g3 = build_agent(
        model=MemoryContinuityModel(), store=store, checkpointer=saver
    )
    r3 = _invoke(
        g3, "new session", user_id, config={"configurable": {"thread_id": thread_2}}
    )
    last3 = str(r3["messages"][-1].content)
    assert "saw=1" in last3, f"new thread must start clean: {last3!r}"
    assert FACT in last3

    assert store.get(("memories", user_id), "/notes.md").value["content"] == FACT


@skip_postgres
def test_postgres_checkpointer_and_store_together():
    user_id = f"pgcombo-{uuid.uuid4().hex[:8]}"
    thread_1 = f"pg-combo-t1-{uuid.uuid4().hex[:6]}"
    thread_2 = f"pg-combo-t2-{uuid.uuid4().hex[:6]}"

    cp_1 = get_checkpointer(POSTGRES_URL)
    st_1 = get_store(POSTGRES_URL)
    try:
        g1 = build_agent(
            model=MemoryContinuityModel(FACT), store=st_1, checkpointer=cp_1
        )
        r1 = _invoke(
            g1, "remember", user_id, config={"configurable": {"thread_id": thread_1}}
        )
        last1 = str(r1["messages"][-1].content)
        assert "saw=1" in last1, f"first session: {last1!r}"
        assert FACT in last1

        # Restart: ALL FIVE objects are fresh (saver, store, graph, thread resume).
        cp_2 = get_checkpointer(POSTGRES_URL)
        st_2 = get_store(POSTGRES_URL)
        try:
            g2 = build_agent(
                model=MemoryContinuityModel(), store=st_2, checkpointer=cp_2
            )
            r2 = _invoke(
                g2, "again", user_id, config={"configurable": {"thread_id": thread_1}}
            )
            last2 = str(r2["messages"][-1].content)
            assert "saw=2" in last2
            assert FACT in last2

            g3 = build_agent(
                model=MemoryContinuityModel(), store=st_2, checkpointer=cp_2
            )
            r3 = _invoke(
                g3, "new session", user_id,
                config={"configurable": {"thread_id": thread_2}},
            )
            last3 = str(r3["messages"][-1].content)
            assert "saw=1" in last3, "brand-new thread starts clean"
            assert FACT in last3, "long-term memory must cross threads"

            item = st_2.get(("memories", user_id), "/notes.md")
            assert item is not None and FACT in item.value["content"]
        finally:
            cp_2.conn.close()
            st_2.conn.close()
    finally:
        for tid in (thread_1, thread_2):
            try:
                cp_1.delete_thread(tid)
            except Exception:
                pass
        try:
            st_1.delete(("memories", user_id), "/notes.md")
        except Exception:
            pass
        cp_1.conn.close()
        st_1.conn.close()


# --------------------------------------------------------------------------- #
# Factory-level sanity                                                        #
# --------------------------------------------------------------------------- #
def test_get_store_defaults_to_in_memory(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    store = get_store()
    assert isinstance(store, InMemoryStore)


def test_get_store_requires_dims_when_embed_given():

    class _FakeEmbed:
        pass

    from src.memory.store import _build_postgres_store

    # No embed -> no index -> PostgresStore built without connection-side error.
    # dims validation happens BEFORE opening a connection, so the production
    # path raising ValueError does not need a reachable DB.
    with pytest.raises(ValueError, match="dims"):
        _build_postgres_store(POSTGRES_URL, embed=_FakeEmbed(), dims=None)


@skip_postgres
def test_get_store_postgres_enforces_dims_with_embed():
    from langgraph.store.postgres import PostgresStore

    class _FakeEmbed:
        pass

    store = get_store(POSTGRES_URL, embed=_FakeEmbed(), dims=64)  # noqa:  # fake embed, never invoked
    try:
        assert isinstance(store, PostgresStore)
    finally:
        store.conn.close()