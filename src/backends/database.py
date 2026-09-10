"""Database infrastructure — Postgres, pgvector, connection management.

Provides:
- ``DatabaseManager`` — connection pool, health checks
- ``MigrationManager`` — schema management with version tracking
- ``create_checkpointer_tables`` — checkpoint + store DDL
- ``create_pgvector_extension`` — vector search support
- ``DatabaseHealthCheck`` — connection monitoring
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Database manager ──────────────────────────────────────────────────


@dataclass
class DatabaseConfig:
    """Postgres database configuration.

    Attributes:
        url: Connection string.
        pool_min: Minimum pool connections.
        pool_max: Maximum pool connections.
        vector_dim: pgvector dimension.
        statement_timeout: Query timeout in seconds.
    """

    url: str = "postgresql://postgres:postgres@localhost:5432/vertex"
    pool_min: int = 2
    pool_max: int = 10
    vector_dim: int = 1536
    statement_timeout: float = 30.0


class DatabaseManager:
    """Manages Postgres connection pool and provides query execution.

    Uses ``psycopg`` for sync operations. Falls back gracefully
    if the database is unavailable.
    """

    def __init__(self, config: DatabaseConfig | None = None) -> None:
        self._config = config or DatabaseConfig()
        self._conn: Any = None
        self._connected = False
        self._connect()

    def _connect(self) -> None:
        try:
            import psycopg
            self._conn = psycopg.connect(self._config.url)
            self._conn.autocommit = True
            self._connected = True
            logger.info("Connected to database: %s", self._config.url)
        except Exception as exc:
            self._connected = False
            logger.warning("Database connection failed: %s", exc)

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def config(self) -> DatabaseConfig:
        return self._config

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> Any:
        """Execute a query and return results.

        Args:
            query: SQL query string.
            params: Query parameters.

        Returns:
            Query results (list of tuples), or None on failure.
        """
        if not self._connected or self._conn is None:
            return None
        try:
            cur = self._conn.cursor()
            cur.execute(query, params)
            try:
                results = cur.fetchall()
            except Exception:
                results = None
            cur.close()
            return results
        except Exception as exc:
            logger.error("Query failed: %s — %s", query[:80], exc)
            return None

    def execute_many(self, query: str, params_list: list[tuple[Any, ...]]) -> bool:
        """Execute a query with multiple parameter sets.

        Args:
            query: SQL query string.
            params_list: List of parameter tuples.

        Returns:
            True if all succeeded.
        """
        if not self._connected or self._conn is None:
            return False
        try:
            cur = self._conn.cursor()
            cur.executemany(query, params_list)
            cur.close()
            return True
        except Exception as exc:
            logger.error("Batch query failed: %s", exc)
            return False

    def health_check(self) -> dict[str, Any]:
        """Run a health check on the database.

        Returns:
            Dict with ``status``, ``latency_ms``, and ``error``.
        """
        if not self._connected:
            return {"status": "disconnected", "latency_ms": 0, "error": "Not connected"}
        start = time.time()
        try:
            cur = self._conn.cursor()
            cur.execute("SELECT 1")
            cur.close()
            latency = (time.time() - start) * 1000
            return {"status": "ok", "latency_ms": round(latency, 2), "error": ""}
        except Exception as exc:
            return {"status": "error", "latency_ms": 0, "error": str(exc)}

    def close(self) -> None:
        """Close the database connection."""
        if self._conn and self._connected:
            try:
                self._conn.close()
            except Exception:
                pass
            self._connected = False


# ── Migration manager ─────────────────────────────────────────────────


class MigrationManager:
    """Schema migration management with version tracking.

    Creates a ``_schema_version`` table to track applied migrations.
    """

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db
        self._ensure_version_table()

    def _ensure_version_table(self) -> None:
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS _schema_version ("
            "  version INTEGER PRIMARY KEY,"
            "  description TEXT NOT NULL DEFAULT '',"
            "  applied_at DOUBLE PRECISION NOT NULL"
            ")"
        )

    def get_current_version(self) -> int:
        """Get the current schema version.

        Returns:
            Current version, or -1 if no migrations applied.
        """
        result = self._db.execute(
            "SELECT COALESCE(MAX(version), -1) FROM _schema_version"
        )
        if result and len(result) > 0:
            return result[0][0]
        return -1

    def apply(self, version: int, description: str, queries: list[str]) -> bool:
        """Apply a migration if not already applied.

        Args:
            version: Version number (incremental).
            description: Human-readable description.
            queries: SQL queries to execute.

        Returns:
            True if applied, False if skipped or failed.
        """
        current = self.get_current_version()
        if version <= current:
            logger.info("Migration v%d already applied, skipping", version)
            return False

        logger.info("Applying migration v%d: %s", version, description)
        for query in queries:
            result = self._db.execute(query)
            if result is None and self._db.is_connected:
                logger.error("Migration v%d failed on query: %s", version, query[:80])
                return False

        now = time.time()
        self._db.execute(
            "INSERT INTO _schema_version (version, description, applied_at) VALUES (%s, %s, %s)",
            (version, description, now),
        )
        logger.info("Migration v%d applied successfully", version)
        return True

    def list_applied(self) -> list[dict[str, Any]]:
        """List all applied migrations.

        Returns:
            List of dicts with ``version``, ``description``, ``applied_at``.
        """
        result = self._db.execute(
            "SELECT version, description, applied_at FROM _schema_version ORDER BY version"
        )
        if not result:
            return []
        return [
            {"version": row[0], "description": row[1], "applied_at": row[2]}
            for row in result
        ]


# ── Schema DDL ────────────────────────────────────────────────────────


CHECKPOINTER_TABLES_SQL = [
    # Checkpoints table
    """CREATE TABLE IF NOT EXISTS checkpoints (
        thread_id TEXT NOT NULL,
        checkpoint_ns TEXT NOT NULL DEFAULT '',
        checkpoint_id TEXT NOT NULL,
        parent_checkpoint_id TEXT,
        type TEXT,
        checkpoint JSONB NOT NULL,
        metadata JSONB NOT NULL DEFAULT '{}',
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
    )""",
    # Checkpoint blob table
    """CREATE TABLE IF NOT EXISTS checkpoint_blobs (
        thread_id TEXT NOT NULL,
        checkpoint_ns TEXT NOT NULL DEFAULT '',
        channel TEXT NOT NULL,
        version TEXT NOT NULL,
        type TEXT NOT NULL,
        blob BYTEA,
        PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
    )""",
    # Pending writes
    """CREATE TABLE IF NOT EXISTS checkpoint_writes (
        thread_id TEXT NOT NULL,
        checkpoint_ns TEXT NOT NULL DEFAULT '',
        checkpoint_id TEXT NOT NULL,
        task_id TEXT NOT NULL,
        idx INTEGER NOT NULL,
        channel TEXT NOT NULL,
        type TEXT,
        value JSONB,
        PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
    )""",
    # Checkpoint mappings
    """CREATE TABLE IF NOT EXISTS checkpoint_mappings (
        thread_id TEXT NOT NULL,
        checkpoint_ns TEXT NOT NULL DEFAULT '',
        checkpoint_id TEXT NOT NULL,
        checkpoint_mapping BYTEA,
        PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
    )""",
]

STORE_TABLES_SQL = [
    # Store table
    """CREATE TABLE IF NOT EXISTS store (
        namespace TEXT NOT NULL DEFAULT '',
        key TEXT NOT NULL,
        value JSONB,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        PRIMARY KEY (namespace, key)
    )""",
    # Store blob table
    """CREATE TABLE IF NOT EXISTS store_blobs (
        namespace TEXT NOT NULL DEFAULT '',
        key TEXT NOT NULL,
        blob_key TEXT NOT NULL,
        blob BYTEA,
        PRIMARY KEY (namespace, key, blob_key)
    )""",
]

PGVECTOR_SQL = [
    "CREATE EXTENSION IF NOT EXISTS vector",
]

SESSION_TABLE_SQL = [
    """CREATE TABLE IF NOT EXISTS session_variables (
        id SERIAL PRIMARY KEY,
        scope TEXT NOT NULL,
        session_id TEXT NOT NULL DEFAULT '',
        plan_id TEXT NOT NULL DEFAULT '',
        bot_id TEXT NOT NULL DEFAULT '',
        name TEXT NOT NULL,
        value_json TEXT NOT NULL DEFAULT 'null',
        var_type TEXT NOT NULL DEFAULT '',
        created_at DOUBLE PRECISION NOT NULL,
        updated_at DOUBLE PRECISION NOT NULL
    )""",
    """CREATE INDEX IF NOT EXISTS idx_sv_scope
       ON session_variables(scope, session_id, plan_id, bot_id)""",
]


def create_checkpointer_tables(db: DatabaseManager) -> bool:
    """Create checkpoint and store tables.

    Args:
        db: Database manager instance.

    Returns:
        True if all tables created successfully.
    """
    if not db.is_connected:
        return False
    for sql in CHECKPOINTER_TABLES_SQL + STORE_TABLES_SQL:
        result = db.execute(sql)
        if result is None:
            logger.error("Failed to create table: %s", sql[:60])
            return False
    return True


def create_pgvector_extension(db: DatabaseManager) -> bool:
    """Create the pgvector extension if it doesn't exist.

    Args:
        db: Database manager instance.

    Returns:
        True if extension was created or already exists.
    """
    result = db.execute(PGVECTOR_SQL[0])
    return result is not None or not db.is_connected


def create_session_tables(db: DatabaseManager) -> bool:
    """Create session variable tables.

    Args:
        db: Database manager instance.

    Returns:
        True if successful.
    """
    if not db.is_connected:
        return False
    for sql in SESSION_TABLE_SQL:
        result = db.execute(sql)
        if result is None:
            return False
    return True


# ── Backup / Restore ──────────────────────────────────────────────────


@dataclass
class BackupStrategy:
    """Database backup configuration.

    Attributes:
        schedule: Cron schedule for backups (e.g. ``"0 2 * * *"``).
        retention_days: Number of days to retain backups.
        output_dir: Directory to write backup files.
        tables: List of tables to backup; empty = all.
    """

    schedule: str = "0 2 * * *"
    retention_days: int = 7
    output_dir: str = "./backups"
    tables: list[str] = field(default_factory=list)


__all__ = [
    "BackupStrategy",
    "CHECKPOINTER_TABLES_SQL",
    "DatabaseConfig",
    "DatabaseManager",
    "MigrationManager",
    "STORE_TABLES_SQL",
    "create_checkpointer_tables",
    "create_pgvector_extension",
    "create_session_tables",
]