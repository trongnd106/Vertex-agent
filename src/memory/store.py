"""Long-term memory store for cross-session persistence.

Provides ``BaseStore`` interface with ``InMemoryStore`` for development
and ``PostgresStore`` for production.  Supports namespace-based isolation,
semantic search via ``pgvector``, and TTL for automatic expiry.
"""

from __future__ import annotations

import copy
import json
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

from src.memory.checkpoint import Checkpoint


# ── Store data types ────────────────────────────────────────────────────


@dataclass
class Item:
    """A single item in the store.

    - ``key``: unique item key within a namespace
    - ``value``: arbitrary JSON-serializable data
    - ``namespace``: tuple path for isolation (e.g. ``("memories", "user_123")``)
    - ``created_at``: creation timestamp
    - ``updated_at``: last-update timestamp
    - ``score``: relevance score from search (populated at query time)
    """

    key: str = ""
    value: Any = None
    namespace: tuple[str, ...] = ()
    created_at: float = 0.0
    updated_at: float = 0.0
    score: float = 0.0
    ttl: float = 0.0  # 0 means no TTL

    def is_expired(self) -> bool:
        """Check if this item has expired."""
        if self.ttl <= 0:
            return False
        return time.time() > self.updated_at + self.ttl

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "namespace": list(self.namespace),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "score": self.score,
        }


@dataclass
class SearchResult:
    """Result of a store search query."""

    items: list[Item] = field(default_factory=list)
    total: int = 0
    offset: int = 0


# ── Base store ──────────────────────────────────────────────────────────


class BaseStore(ABC):
    """Abstract base for long-term memory backends.

    Methods:
        get: Retrieve an item by namespace + key.
        put: Store/update an item.
        search: Search items within a namespace.
        delete: Remove an item.
        list_namespaces: List available namespaces.
    """

    @abstractmethod
    def get(
        self,
        namespace: tuple[str, ...],
        key: str,
    ) -> Item | None:
        """Get an item by namespace and key.

        Args:
            namespace: Namespace tuple (e.g. ``("memories", "user_123")``).
            key: Item key within the namespace.

        Returns:
            The item, or None.
        """
        ...

    @abstractmethod
    def put(
        self,
        namespace: tuple[str, ...],
        key: str,
        value: Any,
        ttl: float = 0.0,
    ) -> Item:
        """Store or update an item.

        Args:
            namespace: Namespace tuple.
            key: Item key.
            value: JSON-serializable value.
            ttl: Time-to-live in seconds (0 = no expiry).

        Returns:
            The stored item.
        """
        ...

    @abstractmethod
    def search(
        self,
        namespace_prefix: tuple[str, ...],
        *,
        query: str | None = None,
        filter: dict[str, Any] | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> SearchResult:
        """Search items within a namespace prefix.

        Args:
            namespace_prefix: Namespace prefix to search under.
            query: Optional text query (semantic if vector index available).
            filter: Optional field-level filters.
            limit: Max results.
            offset: Pagination offset.

        Returns:
            ``SearchResult``.
        """
        ...

    @abstractmethod
    def delete(
        self,
        namespace: tuple[str, ...],
        key: str,
    ) -> bool:
        """Delete an item.

        Returns:
            True if the item existed and was deleted.
        """
        ...

    @abstractmethod
    def list_namespaces(
        self,
        prefix: tuple[str, ...] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[tuple[str, ...]]:
        """List available namespaces.

        Args:
            prefix: Only return namespaces with this prefix.
            limit: Max results.
            offset: Pagination offset.

        Returns:
            List of namespace tuples.
        """
        ...


StoreFilter = dict[str, Any]
"""Type alias for store search filters."""


# ── In-memory store ─────────────────────────────────────────────────────


class InMemoryStore(BaseStore):
    """In-memory implementation of ``BaseStore`` for development/testing.

    Thread-safe.  Supports basic substring matching for ``search``.
    """

    def __init__(self) -> None:
        self._data: dict[tuple[str, ...], dict[str, Item]] = {}
        self._lock = threading.Lock()

    def get(
        self,
        namespace: tuple[str, ...],
        key: str,
    ) -> Item | None:
        with self._lock:
            ns = self._data.get(namespace)
            if ns is None:
                return None
            item = ns.get(key)
            if item is None:
                return None
            if item.is_expired():
                del ns[key]
                return None
            return copy.deepcopy(item)

    def put(
        self,
        namespace: tuple[str, ...],
        key: str,
        value: Any,
        ttl: float = 0.0,
    ) -> Item:
        now = time.time()
        item = Item(
            key=key,
            value=copy.deepcopy(value),
            namespace=namespace,
            created_at=now,
            updated_at=now,
            ttl=ttl,
        )
        with self._lock:
            ns = self._data.setdefault(namespace, {})
            existing = ns.get(key)
            if existing:
                item.created_at = existing.created_at
            ns[key] = copy.deepcopy(item)
        return item

    def search(
        self,
        namespace_prefix: tuple[str, ...],
        *,
        query: str | None = None,
        filter: dict[str, Any] | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> SearchResult:
        with self._lock:
            matching: list[Item] = []
            for ns, items in self._data.items():
                if self._namespace_matches(ns, namespace_prefix):
                    for item in items.values():
                        if item.is_expired():
                            continue
                        if filter and not self._matches_filter(item, filter):
                            continue
                        if query and not self._matches_query(item, query):
                            continue
                        matching.append(copy.deepcopy(item))

        # Sort by updated_at descending
        matching.sort(key=lambda i: i.updated_at, reverse=True)
        total = len(matching)
        page = matching[offset : offset + limit]
        return SearchResult(items=page, total=total, offset=offset)

    def delete(
        self,
        namespace: tuple[str, ...],
        key: str,
    ) -> bool:
        with self._lock:
            ns = self._data.get(namespace)
            if ns and key in ns:
                del ns[key]
                if not ns:
                    del self._data[namespace]
                return True
            return False

    def list_namespaces(
        self,
        prefix: tuple[str, ...] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[tuple[str, ...]]:
        with self._lock:
            namespaces = list(self._data.keys())
        if prefix:
            namespaces = [ns for ns in namespaces if self._namespace_matches(ns, prefix)]
        namespaces.sort()
        return namespaces[offset : offset + limit]

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _namespace_matches(ns: tuple[str, ...], prefix: tuple[str, ...]) -> bool:
        if len(ns) < len(prefix):
            return False
        return ns[: len(prefix)] == prefix

    @staticmethod
    def _matches_filter(item: Item, filter: dict[str, Any]) -> bool:
        for key, expected in filter.items():
            if hasattr(item, key):
                if getattr(item, key) != expected:
                    return False
            elif isinstance(item.value, dict):
                if item.value.get(key) != expected:
                    return False
        return True

    @staticmethod
    def _matches_query(item: Item, query: str) -> bool:
        q = query.lower()
        if q in item.key.lower():
            return True
        if isinstance(item.value, str) and q in item.value.lower():
            return True
        if isinstance(item.value, dict):
            for v in item.value.values():
                if isinstance(v, str) and q in v.lower():
                    return True
        return False


# ── Postgres store ──────────────────────────────────────────────────────


class PostgresStore(BaseStore):
    """PostgreSQL-backed store with optional pgvector support.

    Requires ``psycopg`` and a ``connection_string`` at init.
    Falls back gracefully if ``psycopg`` is not installed.
    """

    def __init__(self, connection_string: str = "") -> None:
        self._conn_string = connection_string
        self._conn: Any = None
        self._lock = threading.Lock()
        self._available = False
        self._init_backend()

    def _init_backend(self) -> None:
        try:
            import psycopg  # noqa: F401

            self._available = True
        except ImportError:
            self._available = False

    def _ensure_connection(self) -> Any:
        if not self._available:
            raise RuntimeError(
                "PostgresStore requires psycopg. Install with: pip install psycopg"
            )
        if self._conn is None:
            import psycopg

            self._conn = psycopg.connect(self._conn_string)
            self._init_schema()
        return self._conn

    def _init_schema(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_store (
                    namespace TEXT[] NOT NULL,
                    key TEXT NOT NULL,
                    value JSONB NOT NULL,
                    created_at DOUBLE PRECISION NOT NULL,
                    updated_at DOUBLE PRECISION NOT NULL,
                    ttl DOUBLE PRECISION NOT NULL DEFAULT 0,
                    embedding vector(1536),
                    PRIMARY KEY (namespace, key)
                );
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_store_namespace
                ON memory_store USING GIN (namespace);
                """
            )
            self._conn.commit()

    def get(self, namespace: tuple[str, ...], key: str) -> Item | None:
        conn = self._ensure_connection()
        with self._lock:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT namespace, key, value, created_at, updated_at, ttl
                FROM memory_store
                WHERE namespace = %s AND key = %s
                """,
                (list(namespace), key),
            )
            row = cur.fetchone()
            if row is None:
                return None
            item = Item(
                key=row[1],
                value=row[2],
                namespace=tuple(row[0]),
                created_at=row[3],
                updated_at=row[4],
                ttl=row[5],
            )
            if item.is_expired():
                self.delete(namespace, key)
                return None
            return item

    def put(self, namespace: tuple[str, ...], key: str, value: Any, ttl: float = 0.0) -> Item:
        now = time.time()
        conn = self._ensure_connection()
        with self._lock:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO memory_store (namespace, key, value, created_at, updated_at, ttl)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (namespace, key)
                DO UPDATE SET value = %s, updated_at = %s, ttl = %s
                """,
                (list(namespace), key, json.dumps(value), now, now, ttl,
                 json.dumps(value), now, ttl),
            )
            conn.commit()
        return Item(
            key=key,
            value=value,
            namespace=namespace,
            created_at=now,
            updated_at=now,
            ttl=ttl,
        )

    def search(
        self,
        namespace_prefix: tuple[str, ...],
        *,
        query: str | None = None,
        filter: dict[str, Any] | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> SearchResult:
        conn = self._ensure_connection()
        with self._lock:
            cur = conn.cursor()
            prefix_list = list(namespace_prefix)
            # Match namespace prefix using array slicing
            cur.execute(
                """
                SELECT namespace, key, value, created_at, updated_at, ttl
                FROM memory_store
                WHERE namespace[1:%s] = %s
                ORDER BY updated_at DESC
                LIMIT %s OFFSET %s
                """,
                (len(prefix_list), prefix_list, limit, offset),
            )
            rows = cur.fetchall()
            items = []
            for row in rows:
                item = Item(
                    key=row[1],
                    value=row[2],
                    namespace=tuple(row[0]),
                    created_at=row[3],
                    updated_at=row[4],
                    ttl=row[5],
                )
                if not item.is_expired():
                    items.append(item)

            # Get total count
            cur.execute(
                """
                SELECT COUNT(*) FROM memory_store
                WHERE namespace[1:%s] = %s
                """,
                (len(prefix_list), prefix_list),
            )
            total = cur.fetchone()[0]

        return SearchResult(items=items, total=total, offset=offset)

    def delete(self, namespace: tuple[str, ...], key: str) -> bool:
        conn = self._ensure_connection()
        with self._lock:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM memory_store WHERE namespace = %s AND key = %s",
                (list(namespace), key),
            )
            conn.commit()
            return cur.rowcount > 0

    def list_namespaces(
        self,
        prefix: tuple[str, ...] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[tuple[str, ...]]:
        conn = self._ensure_connection()
        with self._lock:
            cur = conn.cursor()
            if prefix:
                cur.execute(
                    """
                    SELECT DISTINCT namespace[1:%s] FROM memory_store
                    WHERE namespace[1:%s] = %s
                    ORDER BY namespace
                    LIMIT %s OFFSET %s
                    """,
                    (len(prefix), len(prefix), list(prefix), limit, offset),
                )
            else:
                cur.execute(
                    """
                    SELECT DISTINCT namespace FROM memory_store
                    ORDER BY namespace
                    LIMIT %s OFFSET %s
                    """,
                    (limit, offset),
                )
            return [tuple(row[0]) for row in cur.fetchall()]


__all__ = [
    "BaseStore",
    "InMemoryStore",
    "Item",
    "PostgresStore",
    "SearchResult",
    "StoreFilter",
    "get_store",
    "close_store",
]


def get_store(db_url: str | None = None) -> BaseStore:
    """Factory: return a ``PostgresStore`` when a db_url is given, else ``InMemoryStore``."""
    if db_url:
        return PostgresStore(db_url)
    return InMemoryStore()


def close_store(store: BaseStore) -> None:
    """Close the underlying connection if the store holds one (PostgresStore)."""
    conn = getattr(store, "_conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass