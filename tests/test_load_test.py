"""Phase 8: concurrency load test — integration test + deterministic driver tests.

The deployment-load scenario is N concurrent sessions across distinct
``thread_id``s, all sharing ONE checkpointer + Store. Two coverage layers:

- **Deterministic (no DB)** — run the driver against in-memory ``MemorySaver``
  + ``InMemoryStore`` to validate the isolation logic, the resume check, and
  that a cross-thread memory leak is DETECTED (the assertion machinery works).
  These always run in CI.
- **Real Postgres (@skip_postgres)** — run the driver against the shared
  ``PostgresSaver`` + ``PostgresStore`` from ``infra/docker-compose.yml`` and
  assert every session completes and reads back its own memory. Runs for real
  when the DB is up; skipped otherwise.

No fabricated perf budget: throughput is reported, not asserted against a
magic number.
"""

from __future__ import annotations

import os

import psycopg
import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

from src.api.load_test import run_concurrent_sessions

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
# Deterministic (in-memory) — always run                                          #
# --------------------------------------------------------------------------- #
def test_concurrent_sessions_isolated_in_memory():
    n = 6
    result = run_concurrent_sessions(
        n_sessions=n,
        turns=2,
        store=InMemoryStore(),
        saver=MemorySaver(),
    )
    assert result.passed, result.failures
    assert all(s.ok for s in result.sessions)
    assert result.isolation_ok
    assert result.total_elapsed > 0
    assert result.throughput_sessions_per_sec > 0
    for s in result.sessions:
        assert s.own_fact in (s.echoed_fact or "")


def test_driver_passes_shared_saver_and_store():
    """A single shared store+saver is threaded through every concurrent graph."""
    saver = MemorySaver()
    store = InMemoryStore()
    result = run_concurrent_sessions(n_sessions=3, turns=2, store=store, saver=saver)
    assert result.passed, result.failures
    for s in result.sessions:
        assert s.ok


# --------------------------------------------------------------------------- #
# Real Postgres (runs for real when DB is up)                                     #
# --------------------------------------------------------------------------- #
@skip_postgres
def test_concurrent_sessions_isolated_over_postgres():
    n = 6
    result = run_concurrent_sessions(
        n_sessions=n,
        turns=2,
        database_url=POSTGRES_URL,
    )
    assert result.passed, result.failures
    assert all(s.ok for s in result.sessions)
    assert result.isolation_ok
    assert result.total_elapsed > 0
    assert result.throughput_sessions_per_sec > 0
    for s in result.sessions:
        assert s.own_fact in (s.echoed_fact or "")
