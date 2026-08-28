"""Store factory for long-term (cross-session) memory.

Phase 5 : long-term memory is implemented via a LangGraph **Store**
(``BaseStore``), which survives across threads and process restarts. The
`deepagents.StoreBackend`<->`CompositeBackend` wiring lives in
``src/memory/memory_backend.py``; this module only produces the ``BaseStore``
instance itself, mirroring the checkpointer factory pattern from
``src/memory/checkpointer.py`` (Task 4).

Two backends are supported:

- **dev / test (default)** — ``InMemoryStore`` (in-memory). Fast, deterministic,
  no external dependency. A single *shared* instance passed to two graphs
  simulates a real Store the way ``MemorySaver`` does for the checkpointer:
  session A writes, session B (same instance) reads.
- **production** — ``PostgresStore`` (`langgraph-checkpoint-postgres` 3.x),
  persisted across process restarts. Activation is explicit: either pass
  ``database_url`` or set the ``DATABASE_URL`` environment variable. The
  returned store is *ready to use* (connection open, schema and migrations set
  up) and may be passed straight to ``build_agent(store=store, ...)``.
  Semantic-search indexing is OFF by default; pass ``embed=`` (an embedding
  model) **and** ``dims=`` to enable the pgvector ``store`` index.
"""

from __future__ import annotations

import os
from typing import Any

import psycopg
from psycopg.rows import dict_row

from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore
from langgraph.store.postgres import PostgresStore


def _build_postgres_store(
    database_url: str,
    *,
    embed: Any | None = None,
    dims: int | None = None,
) -> PostgresStore:
    """Open a Postgres connection and return a ``PostgresStore`` ready to use.

    Verified usage pattern against the installed source
    ``langgraph/store/postgres/__init__.py`` / ``base.py`` (3.1.2):

    - ``PostgresStore.from_conn_string(url, index=...)`` is a ``@contextmanager``:
      it opens a ``psycopg.Connection`` (``autocommit=True``,
      ``prepare_threshold=0``, ``row_factory=dict_row``), yields
      ``PostgresStore(conn, index=...)``, and closes the connection when the
      ``with`` block exits. A factory cannot return a store from inside that
      ``with`` if the store must outlive the block.
    - ``PostgresStore.__init__(conn, pipe=None, deserializer=None, index=None,
      ttl=None)`` is public and accepts a raw ``psycopg.Connection`` directly.
    - Each method opens a cursor via ``_internal.get_connection(self.conn)``
      (``store/postgres/base.py:950``), which yields the ``Connection`` as-is,
      exactly like the checkpointer. So a store built on an open ``Connection``
      works for *any number* of invokes, not just inside a single ``with``.

    We therefore mirror exactly what ``from_conn_string`` does internally (same
    connection parameters) but keep the connection open, instantiate the store,
    and run ``setup()`` before returning. The caller owns the connection; close
    it with ``.conn.close()`` when done.

    Args:
        database_url: Postgres connection string.
        embed: Embedding model enabling pgvector semantic search. ``None``
            (default) builds the store **without** an index (no search, no
            pgvector requirement).
        dims: Embedding dimensions, required together with ``embed``.
    """
    index = None
    if embed is not None:
        if dims is None:
            msg = "dims must be provided when embed is set (embedding vector size)."
            raise ValueError(msg)
        index = {"embed": embed, "dims": int(dims)}

    conn = psycopg.connect(
        database_url,
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
    )
    store = PostgresStore(conn, index=index)
    # setup() creates the store schema and applies migrations; it is idempotent
    # (records versions in the store_migrations table) and also creates the
    # vector index when one is configured. Called exactly once per connection.
    store.setup()
    return store


def get_store(
    database_url: str | None = None,
    *,
    embed: Any | None = None,
    dims: int | None = None,
) -> BaseStore:
    """Return a ready-to-use Store for long-term (cross-session) memory.

    Args:
        database_url: Postgres connection string for the **production**
            ``PostgresStore``. If ``None``, falls back to the ``DATABASE_URL``
            environment variable. If neither is set, returns an in-memory
            ``InMemoryStore`` (dev/test default — shared across graphs to
            simulate a real Store).
        embed: Optional embedding model to enable pgvector semantic search on
            the Postgres store. ``None`` (default) → no index.
        dims: Embedding dimensions, required when ``embed`` is provided.

    Returns:
        An ``InMemoryStore`` (dev) or an entered, schema-set-up
        ``PostgresStore`` (production). When no semantic-search index is
        configured the store is still fully usable as a per-user by-path
        memory namespace (``get``/``put``/``search`` by key); only the
        vector ``query`` search is unavailable.

    Note on connection ownership (production): the caller owns the underlying
    Postgres connection and must close it with ``store.conn.close()`` when
    done (no ``with`` block is returned). See ``_build_postgres_store``.
    """
    url = database_url or os.environ.get("DATABASE_URL")
    if url:
        return _build_postgres_store(url, embed=embed, dims=dims)
    return InMemoryStore()


__all__ = ["get_store", "_build_postgres_store"]