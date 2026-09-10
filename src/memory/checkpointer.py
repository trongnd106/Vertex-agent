"""Checkpointer factory for short-term (per-session) memory.

Phase 4 : Session memory is implemented purely via a LangGraph **checkpointer**.
The checkpointer auto-persists the *entire* graph state (messages, tool calls,
intermediate results and the virtual filesystem) after every step, keyed by
`thread_id`. Resuming a session is just invoking the same compiled graph (or a
fresh graph over the same checkpointer) with the same
`config={"configurable": {"thread_id": ...}}`.

Two backends are supported:

- **dev / test (default)** — `MemorySaver` (in-memory). Fast, no external
  dependency, but lost on process restart.
- **production** — `PostgresSaver` (`langgraph-checkpoint-postgres` 3.x),
  persisted across process restarts. Activation is explicit: either pass
  `database_url` or set the `DATABASE_URL` environment variable. The returned
  saver is *ready to use* (connection open, schema set up) and may be passed
  straight to `create_deep_agent(..., checkpointer=saver)`.
"""

from __future__ import annotations

import os

import psycopg

from src.config import config
from langgraph.checkpoint.base import BaseCheckpointSaver
from psycopg.rows import dict_row
from langgraph.checkpoint.memory import MemorySaver

from langgraph.checkpoint.postgres import PostgresSaver


def _build_postgres_saver(database_url: str) -> PostgresSaver:
    """Open a Postgres connection and return a ``PostgresSaver`` ready to use.

    Verified usage pattern against the installed source
    ``langgraph/checkpoint/postgres/__init__.py`` (3.1.2):

    - ``PostgresSaver.from_conn_string(url)`` is a ``@contextmanager``: it opens a
      ``psycopg.Connection`` (``autocommit=True``, ``prepare_threshold=0``,
      ``row_factory=dict_row``), yields ``PostgresSaver(conn)``, and closes the
      connection when the ``with`` block exits. A factory cannot return a saver
      from inside that ``with`` if the saver must outlive the block.
    - ``PostgresSaver.__init__(conn, pipe=None, serde=None)`` is public and
      accepts a raw ``psycopg.Connection`` directly.
    - Each method opens a cursor via ``_internal.get_connection(self.conn)``
      (``postgres/_internal.py``), which yields the ``Connection`` as-is. So a
      saver built on an open ``Connection`` works for *any number* of invokes,
      not just inside a single ``with`` block.

    We therefore mirror exactly what ``from_conn_string`` does internally
    (same connection parameters) but keep the connection open, instantiate the
    saver, and run ``setup()`` before returning. The caller owns the connection;
    close it with ``.conn.close()`` when done.
    """
    conn = psycopg.connect(
        database_url,
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
    )
    saver = PostgresSaver(conn)
    # setup() creates the schema and records migration versions; it is idempotent
    # (checks checkpoint_migrations and applies only missing migrations).
    saver.setup()
    return saver


def get_checkpointer(database_url: str | None = None) -> BaseCheckpointSaver:
    """Return a ready-to-use checkpointer for short-term session memory.

    Args:
        database_url: Postgres connection string for the **production**
            ``PostgresSaver``. If ``None``, falls back to the ``DATABASE_URL``
            environment variable. If neither is set, returns the in-memory
            ``MemorySaver`` (dev/test default).

    Returns:
        A ``MemorySaver`` (dev) or an entered, schema-set-up ``PostgresSaver``
        (production).
    """
    url = database_url or config.DATABASE_URL
    if url:
        return _build_postgres_saver(url)
    return MemorySaver()


__all__ = ["get_checkpointer", "_build_postgres_saver"]
