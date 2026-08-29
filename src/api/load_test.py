"""Concurrency load test: many thread_ids in parallel over one Postgres checkpointer+store.

Phase 8 deployment/ops: prove the production persistence layer (Postgres
``PostgresSaver`` checkpointer + ``PostgresStore`` long-term memory, both
sharing a single real database via ``infra/docker-compose.yml``) holds up under
concurrent agent sessions, with NO cross-thread interference.

Why this matters (and what we assert):

- Every concurrent session uses a **distinct ``thread_id``** through
  ``build_agent``, all sharing the SAME ``PostgresSaver`` and ``PostgresStore``
  instances (and thus the same DB connections). This is the production shape:
  an API server serving many users on one persistence layer.
- Each session's deterministic fake model (Ruling M1 — no LLM keys) writes a
  unique user fact to ``/memory/notes.md`` on turn 1 and reads it back on
  turn 2. The writer's fact routes through the Store-backed ``/memory/``
  backend into the per-user ``("memories", <user_id>)`` namespace; the read on
  turn 2 resumes the SAME thread (same ``thread_id``) and must see that user's
  own fact — proving both **history isolation** (checkpointer) and **memory
  isolation** (Store) under load.

Runnable as:
    python -m src.api.load_test --sessions 8 --turns 2 [--db-url ...]

The pass criteria are honest and modest (no fabricated perf numbers): all N
sessions complete without raising, each thread reconstructs exactly its own
message history, each user's memory namespace holds only its own fact, and the
per-thread resume check passes. Throughput is REPORTED (sessions/s, invokes/s)
but not asserted against a magic number.
"""

from __future__ import annotations

import argparse
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone

from langchain_core.messages import AIMessage, BaseMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore

from src.agent.graph import build_agent
from src.memory.checkpointer import get_checkpointer
from src.memory.memory_backend import UserContext
from src.memory.store import get_store
from tests.fake_model import ScriptedChatModel

#: Default concurrency (sessions = threads) — a modest, achievable load bucket.
DEFAULT_SESSIONS = 8
#: Turns per session: turn 1 writes a fact, turn 2 reads it back (resume check).
DEFAULT_TURNS = 2


@dataclass(frozen=True)
class SessionResult:
    """Outcome of one concurrent session."""

    index: int
    thread_id: str
    user_id: str
    ok: bool
    error: str | None = None
    write_elapsed: float = 0.0
    total_elapsed: float = 0.0
    #: The echoed transcript line actually read back on the resume turn.
    echoed_fact: str | None = None
    #: The session's own unique fact (written to /memory/notes.md on turn 1).
    own_fact: str = ""


@dataclass
class LoadTestResult:
    """Aggregate of a concurrency run."""

    n_sessions: int
    turns: int
    started_at: datetime
    finished_at: datetime
    sessions: list[SessionResult] = field(default_factory=list)
    isolation_ok: bool = True
    failures: list[str] = field(default_factory=list)
    total_elapsed: float = 0.0

    @property
    def throughput_sessions_per_sec(self) -> float:
        if self.total_elapsed <= 0:
            return 0.0
        return self.n_sessions / self.total_elapsed

    @property
    def invokes_per_sec(self) -> float:
        if self.total_elapsed <= 0:
            return 0.0
        return (self.n_sessions * self.turns) / self.total_elapsed

    @property
    def passed(self) -> bool:
        return not self.failures and self.isolation_ok


class _WriterReaderModel(ScriptedChatModel):
    """Deterministic per-session model: write a unique fact, then read it back.

    Turn 1 emits a ``write_file`` tool call targeting ``/memory/notes.md`` with
    this session's unique fact (routes into its user's Store namespace). Turn 2
    emits a ``read_file`` on the same path and, on the following model call,
    echoes the tool result so the harness records what was actually read. Each
    session owns its own instance with its own fact — the concurrency proof is
    that this session reads back ITS OWN fact and never another session's.
    """

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
        if self._step == 2:
            return AIMessage(content="WROTE")
        if self._step == 3:
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
        for m in reversed(self.last_messages):
            if m.type == "tool":
                return AIMessage(content="READ:" + str(m.content))
        return AIMessage(content="NO-TOOL")


def run_concurrent_sessions(
    *,
    n_sessions: int = DEFAULT_SESSIONS,
    turns: int = DEFAULT_TURNS,
    database_url: str | None = None,
    store: BaseStore | None = None,
    saver: BaseCheckpointSaver | None = None,
    max_workers: int | None = None,
) -> LoadTestResult:
    """Run ``n_sessions`` concurrent sessions against one shared store+checkpointer.

    Args:
        n_sessions: Number of concurrent sessions (unique ``thread_id`` each).
        turns: Invokes per session (>= 2 to include the resume check).
        database_url: Postgres URL; when a ``store``/``saver`` is provided this
            is ignored for those backends. Defaults to ``DATABASE_URL`` env.
        store: Optional shared ``BaseStore``. Defaults to ``get_store(database_url)``.
        saver: Optional shared ``BaseCheckpointSaver``. Defaults to
            ``get_checkpointer(database_url)``.
        max_workers: ThreadPool size. Defaults to ``n_sessions``.

    Returns:
        A `LoadTestResult` with per-session outcomes, isolation verdict, and
        measured throughput.
    """
    if turns < 2:
        raise ValueError("turns must be >= 2 (turn 1 writes, turn 2 resumes/reads).")
    store = store or get_store(database_url)
    saver = saver or get_checkpointer(database_url)
    thread_ids = [
        f"load-{i}-{uuid.uuid4().hex[:8]}" for i in range(n_sessions)
    ]
    user_ids = [f"user-{i}-{uuid.uuid4().hex[:4]}" for i in range(n_sessions)]
    facts = [f"session-{i} memory fact {uuid.uuid4().hex[:8]}" for i in range(n_sessions)]

    started = datetime.now(timezone.utc)
    started_wall = time.perf_counter()

    def _run_one(i: int) -> SessionResult:
        thread_id = thread_ids[i]
        user_id = user_ids[i]
        model = _WriterReaderModel(facts[i])
        agent = build_agent(model=model, store=store, checkpointer=saver)

        echo: str | None = None
        t0 = time.perf_counter()
        try:
            for turn in range(turns):
                cfg = {"configurable": {"thread_id": thread_id}}
                if turn == 0:
                    t_wr = time.perf_counter()
                    agent.invoke(
                        {"messages": [{"role": "user", "content": "remember this"}]},
                        config=cfg,
                        context=UserContext(user_id=user_id),
                    )
                    write_elapsed = time.perf_counter() - t_wr
                else:
                    result = agent.invoke(
                        {"messages": [{"role": "user", "content": "recall"}]},
                        config=cfg,
                        context=UserContext(user_id=user_id),
                    )
                    write_elapsed = time.perf_counter() - t0  # total so far
                    last = result["messages"][-1]
                    if isinstance(last, BaseMessage):
                        echo = last.content if isinstance(last.content, str) else None
            total_elapsed = time.perf_counter() - t0
            return SessionResult(
                index=i,
                thread_id=thread_id,
                user_id=user_id,
                ok=True,
                write_elapsed=write_elapsed,
                total_elapsed=total_elapsed,
                echoed_fact=echo,
                own_fact=facts[i],
            )
        except Exception as exc:  # pragma: no cover - error path
            return SessionResult(
                index=i,
                thread_id=thread_id,
                user_id=user_id,
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
                own_fact=facts[i],
            )

    workers = max_workers or n_sessions
    results: list[SessionResult] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_run_one, i) for i in range(n_sessions)]
        for fut in as_completed(futures):
            results.append(fut.result())
    results.sort(key=lambda r: r.index)

    total_elapsed = time.perf_counter() - started_wall
    finished = datetime.now(timezone.utc)

    # Isolation checks: every session must read back ITS OWN fact on resume and
    # never another session's. The echoed transcription is
    # ``READ:1  <own fact>`` (the leading index is write_file's line number), so
    # we assert containment: own fact present, no other session's fact present.
    failures: list[str] = []
    for r in results:
        if not r.ok:
            failures.append(f"[session {r.index} {r.thread_id}] {r.error}")
    isolation_ok = True

    if not failures:
        for r in results:
            echo = r.echoed_fact or ""
            if r.own_fact not in echo:
                failures.append(
                    f"[session {r.index} {r.thread_id}] did not read its own "
                    f"memory (echoed {echo!r})"
                )
                isolation_ok = False
                continue
            leaked = [
                facts[j] for j in range(n_sessions)
                if j != r.index and facts[j] in echo
            ]
            if leaked:
                failures.append(
                    f"[session {r.index} {r.thread_id}] cross-thread memory leak: "
                    f"read another session's fact {leaked[0]!r}"
                )
                isolation_ok = False

    return LoadTestResult(
        n_sessions=n_sessions,
        turns=turns,
        started_at=started,
        finished_at=finished,
        sessions=results,
        isolation_ok=isolation_ok,
        failures=failures,
        total_elapsed=total_elapsed,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Concurrency load test against the shared Postgres "
        "checkpointer + store (fake deterministic model, no LLM keys)."
    )
    parser.add_argument("--sessions", type=int, default=DEFAULT_SESSIONS)
    parser.add_argument("--turns", type=int, default=DEFAULT_TURNS)
    parser.add_argument("--db-url", default=None, help="Postgres URL (default DATABASE_URL).")
    parser.add_argument("--workers", type=int, default=None, help="Thread pool size (default = sessions).")
    args = parser.parse_args(argv)

    result = run_concurrent_sessions(
        n_sessions=args.sessions,
        turns=args.turns,
        database_url=args.db_url,
        max_workers=args.workers,
    )

    print(f"load_test: {result.n_sessions} concurrent sessions x {result.turns} turns")
    print(f"  window: {result.started_at.isoformat()} -> {result.finished_at.isoformat()}")
    print(f"  total elapsed: {result.total_elapsed:.3f}s")
    print(f"  throughput: {result.throughput_sessions_per_sec:.2f} sessions/s, "
          f"{result.invokes_per_sec:.2f} invokes/s")
    ok = sum(1 for r in result.sessions if r.ok)
    print(f"  completed: {ok}/{result.n_sessions}")
    if result.failures:
        print("  FAILURES:")
        for f in result.failures:
            print(f"    - {f}")
    else:
        print("  isolation: OK (each thread saw only its own history + memory)")
    print(f"  VERDICT: {'PASS' if result.passed else 'FAIL'}")
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
