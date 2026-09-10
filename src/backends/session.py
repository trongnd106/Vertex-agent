"""Session state management — store and retrieve variables per session.

Provides:
- ``SessionStateBackend`` — abstract interface
- ``InMemorySessionBackend`` — dict-based, for testing
- ``RedisSessionBackend`` — Redis-backed, production (connection pool)
- ``DatabaseSessionBackend`` — Postgres-backed, persistent
- ``VariableScope`` — plan / bot / sys scopes
"""

from __future__ import annotations

import abc
import json
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ── Variable scope ────────────────────────────────────────────────────


class VariableScope(str, Enum):
    PLAN = "plan"  # Within a single plan execution
    BOT = "bot"  # Cross-session, per-bot
    SYS = "sys"  # System global


# ── Variable ──────────────────────────────────────────────────────────


@dataclass
class SessionVariable:
    """A stored session variable.

    Attributes:
        name: Variable name.
        value: Variable value (JSON-serializable).
        scope: The scope this variable belongs to.
        session_id: Session identifier.
        plan_id: Plan identifier (optional).
        bot_id: Bot identifier (optional).
        var_type: Auto-detected JSON type.
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
    """

    name: str = ""
    value: Any = None
    scope: VariableScope = VariableScope.PLAN
    session_id: str = ""
    plan_id: str = ""
    bot_id: str = ""
    var_type: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0

    def __post_init__(self) -> None:
        if not self.var_type:
            self.var_type = self._detect_type()
        now = time.time()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    def _detect_type(self) -> str:
        if isinstance(self.value, bool):
            return "boolean"
        if isinstance(self.value, int):
            return "integer"
        if isinstance(self.value, float):
            return "number"
        if isinstance(self.value, str):
            return "string"
        if isinstance(self.value, list):
            return "array"
        if isinstance(self.value, dict):
            return "object"
        if self.value is None:
            return "null"
        return "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "scope": self.scope.value,
            "session_id": self.session_id,
            "plan_id": self.plan_id,
            "bot_id": self.bot_id,
            "var_type": self.var_type,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# ── Abstract session state backend ────────────────────────────────────


class SessionStateBackend(abc.ABC):
    """Abstract interface for session state backends."""

    @abc.abstractmethod
    def store_variable(
        self,
        scope: VariableScope,
        session_id: str,
        plan_id: str,
        bot_id: str,
        name: str,
        value: Any,
        var_type: str = "",
    ) -> bool:
        """Store a variable.

        Args:
            scope: Variable scope.
            session_id: Session identifier.
            plan_id: Plan identifier.
            bot_id: Bot identifier.
            name: Variable name.
            value: Variable value.
            var_type: Optional type override.

        Returns:
            True if stored successfully.
        """

    @abc.abstractmethod
    def get_variable(
        self,
        execution: dict[str, Any],
        name: str,
    ) -> Any:
        """Get a variable.

        Args:
            execution: Dict with keys ``session_id``, ``plan_id``,
                       ``bot_id``, and optionally ``scope``.
            name: Variable name.

        Returns:
            The variable value, or None.
        """

    @abc.abstractmethod
    def list_variables(
        self,
        scope: VariableScope | None = None,
        session_id: str = "",
        plan_id: str = "",
        bot_id: str = "",
    ) -> list[SessionVariable]:
        """List variables matching filters."""

    @abc.abstractmethod
    def delete_variable(self, name: str, scope: VariableScope, session_id: str = "") -> bool:
        """Delete a variable.

        Returns:
            True if deleted.
        """


# ── InMemorySessionBackend ────────────────────────────────────────────


class InMemorySessionBackend(SessionStateBackend):
    """Dict-based session state backend, for testing/development."""

    def __init__(self) -> None:
        self._store: dict[str, SessionVariable] = {}
        self._lock = threading.Lock()

    def _key(
        self,
        scope: VariableScope,
        session_id: str,
        plan_id: str,
        bot_id: str,
        name: str,
    ) -> str:
        return f"{scope.value}:{session_id}:{plan_id}:{bot_id}:{name}"

    def store_variable(
        self,
        scope: VariableScope,
        session_id: str,
        plan_id: str,
        bot_id: str,
        name: str,
        value: Any,
        var_type: str = "",
    ) -> bool:
        var = SessionVariable(
            name=name,
            value=value,
            scope=scope,
            session_id=session_id,
            plan_id=plan_id,
            bot_id=bot_id,
            var_type=var_type,
        )
        key = self._key(scope, session_id, plan_id, bot_id, name)
        with self._lock:
            existing = self._store.get(key)
            if existing:
                var.created_at = existing.created_at
            var.updated_at = time.time()
            self._store[key] = var
        return True

    def get_variable(self, execution: dict[str, Any], name: str) -> Any:
        session_id = execution.get("session_id", "")
        plan_id = execution.get("plan_id", "")
        bot_id = execution.get("bot_id", "")
        scope = execution.get("scope", VariableScope.PLAN)
        if isinstance(scope, str):
            scope = VariableScope(scope)

        # Plan scope: exact match session_id + plan_id
        key_plan = self._key(scope, session_id, plan_id, bot_id, name)
        with self._lock:
            var = self._store.get(key_plan)
            if var is not None:
                return var.value

        # Bot scope: match any session_id
        key_bot = self._key(VariableScope.BOT, "", "", bot_id, name)
        var = self._store.get(key_bot)
        if var is not None:
            return var.value

        # Sys scope: global
        key_sys = self._key(VariableScope.SYS, "", "", "", name)
        var = self._store.get(key_sys)
        if var is not None:
            return var.value
        return None

    def list_variables(
        self,
        scope: VariableScope | None = None,
        session_id: str = "",
        plan_id: str = "",
        bot_id: str = "",
    ) -> list[SessionVariable]:
        results: list[SessionVariable] = []
        with self._lock:
            for var in self._store.values():
                if scope and var.scope != scope:
                    continue
                if session_id and var.session_id != session_id:
                    continue
                if plan_id and var.plan_id != plan_id:
                    continue
                if bot_id and var.bot_id != bot_id:
                    continue
                results.append(var)
        return results

    def delete_variable(self, name: str, scope: VariableScope, session_id: str = "") -> bool:
        with self._lock:
            keys = list(self._store.keys())
            for k in keys:
                if k.endswith(f":{name}") and scope.value in k:
                    if not session_id or session_id in k:
                        del self._store[k]
                        return True
        return False


# ── RedisSessionBackend ───────────────────────────────────────────────


class RedisSessionBackend(SessionStateBackend):
    """Redis-backed session state with connection pool.

    Falls back to in-memory if the ``redis`` package is unavailable.
    """

    def __init__(self, url: str = "redis://localhost:6379/0") -> None:
        self._url = url
        self._pool: Any = None
        self._fallback = InMemorySessionBackend()
        self._redis_available = self._init_redis()

    def _init_redis(self) -> bool:
        try:
            import redis
            self._pool = redis.ConnectionPool.from_url(self._url)
            self._client = redis.Redis(connection_pool=self._pool)
            self._client.ping()
            return True
        except Exception:
            self._client = None
            return False

    def _key(
        self,
        scope: VariableScope,
        session_id: str,
        plan_id: str,
        bot_id: str,
        name: str,
    ) -> str:
        return f"session:{scope.value}:{session_id}:{plan_id}:{bot_id}:{name}"

    def store_variable(
        self,
        scope: VariableScope,
        session_id: str,
        plan_id: str,
        bot_id: str,
        name: str,
        value: Any,
        var_type: str = "",
    ) -> bool:
        if not self._redis_available or self._client is None:
            return self._fallback.store_variable(
                scope, session_id, plan_id, bot_id, name, value, var_type
            )
        key = self._key(scope, session_id, plan_id, bot_id, name)
        var = SessionVariable(
            name=name,
            value=value,
            scope=scope,
            session_id=session_id,
            plan_id=plan_id,
            bot_id=bot_id,
            var_type=var_type,
        )
        try:
            self._client.set(key, json.dumps(var.to_dict()))
            return True
        except Exception:
            return False

    def get_variable(self, execution: dict[str, Any], name: str) -> Any:
        if not self._redis_available or self._client is None:
            return self._fallback.get_variable(execution, name)
        session_id = execution.get("session_id", "")
        plan_id = execution.get("plan_id", "")
        bot_id = execution.get("bot_id", "")
        scope = execution.get("scope", VariableScope.PLAN)
        if isinstance(scope, str):
            scope = VariableScope(scope)

        for s in [scope, VariableScope.BOT, VariableScope.SYS]:
            sid = session_id if s == VariableScope.PLAN else ""
            pid = plan_id if s == VariableScope.PLAN else ""
            bid = bot_id if s in (VariableScope.PLAN, VariableScope.BOT) else ""
            key = self._key(s, sid, pid, bid, name)
            try:
                data = self._client.get(key)
                if data:
                    parsed = json.loads(data)
                    return parsed.get("value")
            except Exception:
                continue
        return None

    def list_variables(
        self,
        scope: VariableScope | None = None,
        session_id: str = "",
        plan_id: str = "",
        bot_id: str = "",
    ) -> list[SessionVariable]:
        if not self._redis_available or self._client is None:
            return self._fallback.list_variables(scope, session_id, plan_id, bot_id)
        return []

    def delete_variable(self, name: str, scope: VariableScope, session_id: str = "") -> bool:
        if not self._redis_available or self._client is None:
            return self._fallback.delete_variable(name, scope, session_id)
        try:
            pattern = f"session:{scope.value}:{session_id}:*:*:{name}"
            keys = self._client.keys(pattern)
            if keys:
                self._client.delete(*keys)
                return True
            return False
        except Exception:
            return False


# ── DatabaseSessionBackend ────────────────────────────────────────────


class DatabaseSessionBackend(SessionStateBackend):
    """Postgres-backed persistent session state.

    Uses the ``psycopg`` package. Creates a ``session_variables`` table
    if it doesn't exist.
    """

    def __init__(self, db_url: str) -> None:
        self._db_url = db_url
        self._conn: Any = None
        self._connected = False
        self._init_db()

    def _init_db(self) -> None:
        try:
            import psycopg
            self._conn = psycopg.connect(self._db_url)
            self._conn.autocommit = True
            self._connected = True
            self._create_table()
        except Exception:
            self._fallback = InMemorySessionBackend()

    def _create_table(self) -> None:
        try:
            cur = self._conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS session_variables (
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
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_sv_scope
                ON session_variables(scope, session_id, plan_id, bot_id)
            """)
            cur.close()
        except Exception:
            pass

    def store_variable(
        self,
        scope: VariableScope,
        session_id: str,
        plan_id: str,
        bot_id: str,
        name: str,
        value: Any,
        var_type: str = "",
    ) -> bool:
        if not self._connected:
            return self._fallback.store_variable(
                scope, session_id, plan_id, bot_id, name, value, var_type
            )
        now = time.time()
        var = SessionVariable(
            name=name,
            value=value,
            scope=scope,
            session_id=session_id,
            plan_id=plan_id,
            bot_id=bot_id,
            var_type=var_type,
            created_at=now,
            updated_at=now,
        )
        try:
            cur = self._conn.cursor()
            cur.execute(
                """INSERT INTO session_variables
                   (scope, session_id, plan_id, bot_id, name, value_json, var_type, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (
                    scope.value,
                    session_id,
                    plan_id,
                    bot_id,
                    name,
                    json.dumps(value),
                    var.var_type,
                    var.created_at,
                    var.updated_at,
                ),
            )
            cur.close()
            return True
        except Exception:
            return False

    def get_variable(self, execution: dict[str, Any], name: str) -> Any:
        if not self._connected:
            return self._fallback.get_variable(execution, name)
        session_id = execution.get("session_id", "")
        plan_id = execution.get("plan_id", "")
        bot_id = execution.get("bot_id", "")
        scope = execution.get("scope", VariableScope.PLAN)
        if isinstance(scope, str):
            scope = VariableScope(scope)
        try:
            cur = self._conn.cursor()
            # Try plan scope first
            cur.execute(
                "SELECT value_json FROM session_variables WHERE scope=%s AND session_id=%s AND plan_id=%s AND name=%s",
                (scope.value, session_id, plan_id, name),
            )
            row = cur.fetchone()
            if row:
                cur.close()
                return json.loads(row[0])

            # Bot scope
            cur.execute(
                "SELECT value_json FROM session_variables WHERE scope='bot' AND bot_id=%s AND name=%s",
                (bot_id, name),
            )
            row = cur.fetchone()
            if row:
                cur.close()
                return json.loads(row[0])

            # Sys scope
            cur.execute(
                "SELECT value_json FROM session_variables WHERE scope='sys' AND name=%s",
                (name,),
            )
            row = cur.fetchone()
            if row:
                cur.close()
                return json.loads(row[0])

            cur.close()
            return None
        except Exception:
            return None

    def list_variables(
        self,
        scope: VariableScope | None = None,
        session_id: str = "",
        plan_id: str = "",
        bot_id: str = "",
    ) -> list[SessionVariable]:
        if not self._connected:
            return self._fallback.list_variables(scope, session_id, plan_id, bot_id)
        results: list[SessionVariable] = []
        try:
            cur = self._conn.cursor()
            query = "SELECT scope, session_id, plan_id, bot_id, name, value_json, var_type, created_at, updated_at FROM session_variables WHERE 1=1"
            params: list[Any] = []
            if scope:
                query += " AND scope=%s"
                params.append(scope.value)
            if session_id:
                query += " AND session_id=%s"
                params.append(session_id)
            if plan_id:
                query += " AND plan_id=%s"
                params.append(plan_id)
            if bot_id:
                query += " AND bot_id=%s"
                params.append(bot_id)
            cur.execute(query, params)
            for row in cur.fetchall():
                results.append(
                    SessionVariable(
                        name=row[4],
                        value=json.loads(row[5]),
                        scope=VariableScope(row[0]),
                        session_id=row[1],
                        plan_id=row[2],
                        bot_id=row[3],
                        var_type=row[6],
                        created_at=row[7],
                        updated_at=row[8],
                    )
                )
            cur.close()
        except Exception:
            pass
        return results

    def delete_variable(self, name: str, scope: VariableScope, session_id: str = "") -> bool:
        if not self._connected:
            return self._fallback.delete_variable(name, scope, session_id)
        try:
            cur = self._conn.cursor()
            cur.execute(
                "DELETE FROM session_variables WHERE name=%s AND scope=%s",
                (name, scope.value),
            )
            deleted = cur.rowcount > 0
            cur.close()
            return deleted
        except Exception:
            return False


__all__ = [
    "DatabaseSessionBackend",
    "InMemorySessionBackend",
    "RedisSessionBackend",
    "SessionStateBackend",
    "SessionVariable",
    "VariableScope",
]