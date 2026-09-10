"""Memory backend — Store-backed virtual filesystem and composite routing.

Provides:
- ``StoreBackend`` — presents the ``BaseStore`` as a virtual filesystem
- ``CompositeBackend`` — routes ``/memory/`` paths to ``StoreBackend``,
  everything else to a real filesystem backend
- ``UserContext`` — per-user identity for namespace isolation
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from src.memory.store import BaseStore, InMemoryStore, Item


# Namespace factory: creates a namespace tuple from a user context
NamespaceFactory = Callable[["UserContext"], tuple[str, ...]]


@dataclass
class UserContext:
    """User identity for per-user namespace isolation."""

    user_id: str
    username: str = ""
    roles: list[str] = field(default_factory=list)


# ── Store-backed virtual filesystem ─────────────────────────────────────


class StoreBackend:
    """Backend that presents a ``BaseStore`` as a virtual filesystem.

    Paths like ``/memory/notes.md`` are mapped to store items where:
    - namespace is derived from ``UserContext`` via ``NamespaceFactory``
    - key is the file path within the memory prefix

    Each "file" is stored as a store item with the file content in ``value["content"]``.
    """

    def __init__(
        self,
        store: BaseStore | None = None,
        namespace_factory: NamespaceFactory | None = None,
        memory_prefix: str = "/memory/",
    ) -> None:
        self._store = store or InMemoryStore()
        self._namespace_factory = namespace_factory or (
            lambda ctx: ("memories", ctx.user_id)
        )
        self._memory_prefix = memory_prefix

    @property
    def store(self) -> BaseStore:
        """The underlying store."""
        return self._store

    def _key_from_path(self, path: str) -> str:
        """Convert a filesystem path to a store key.

        Strips the memory prefix and normalizes.
        """
        if path.startswith(self._memory_prefix):
            key = path[len(self._memory_prefix) :]
        else:
            key = path
        return key.strip("/")

    def read_file(self, path: str, user: UserContext | None = None) -> Item | None:
        """Read a virtual file, returning its store ``Item``.

        Args:
            path: Virtual filesystem path.
            user: Current user context (for namespace resolution).

        Returns:
            Store item or None if not found.
        """
        ns = self._namespace_factory(user) if user else ("memories", "default")
        key = self._key_from_path(path)
        return self._store.get(ns, key)

    def write_file(
        self,
        path: str,
        content: str,
        user: UserContext | None = None,
        metadata: dict[str, Any] | None = None,
        ttl: float = 0.0,
    ) -> Item:
        """Write to a virtual file.

        Args:
            path: Virtual filesystem path.
            content: File content.
            user: Current user context.
            metadata: Additional metadata to store alongside content.
            ttl: Time-to-live in seconds.

        Returns:
            The stored item.
        """
        ns = self._namespace_factory(user) if user else ("memories", "default")
        key = self._key_from_path(path)
        value: dict[str, Any] = {"content": content}
        if metadata:
            value["metadata"] = metadata
        return self._store.put(ns, key, value, ttl=ttl)

    def delete_file(self, path: str, user: UserContext | None = None) -> bool:
        """Delete a virtual file.

        Args:
            path: Virtual filesystem path.
            user: Current user context.

        Returns:
            True if the file existed and was deleted.
        """
        ns = self._namespace_factory(user) if user else ("memories", "default")
        key = self._key_from_path(path)
        return self._store.delete(ns, key)

    def list_files(
        self,
        user: UserContext | None = None,
        prefix: str = "",
    ) -> list[Item]:
        """List virtual files for the user.

        Args:
            user: Current user context.
            prefix: Additional key prefix filter.

        Returns:
            List of store items.
        """
        ns = self._namespace_factory(user) if user else ("memories", "default")
        search_prefix = ns
        results = self._store.search(search_prefix)
        if prefix:
            results.items = [i for i in results.items if i.key.startswith(prefix)]
        return results.items


# ── Composite backend ───────────────────────────────────────────────────


class CompositeBackend:
    """Routes paths to the appropriate backend.

    - ``/memory/`` paths → ``StoreBackend`` (virtual filesystem)
    - All other paths → real filesystem (``os.path`` based)
    """

    def __init__(self, store_backend: StoreBackend | None = None) -> None:
        self._store_backend = store_backend or StoreBackend()

    @property
    def store_backend(self) -> StoreBackend:
        return self._store_backend

    def read_file(
        self,
        path: str,
        user: UserContext | None = None,
    ) -> dict[str, Any] | None:
        """Read a file, routing based on path prefix.

        Returns:
            Dict with ``content`` and ``metadata`` keys, or None.
        """
        if path.startswith("/memory/"):
            item = self._store_backend.read_file(path, user=user)
            if item is None:
                return None
            if isinstance(item.value, dict):
                return item.value
            return {"content": str(item.value)}
        else:
            # Real filesystem
            p = Path(path)
            if not p.exists() or not p.is_file():
                return None
            return {
                "content": p.read_text(encoding="utf-8", errors="replace"),
                "metadata": {"size": p.stat().st_size},
            }

    def write_file(
        self,
        path: str,
        content: str,
        user: UserContext | None = None,
    ) -> bool:
        """Write a file, routing based on path prefix.

        Args:
            path: File path.
            content: Content to write.
            user: User context (required for ``/memory/`` paths).

        Returns:
            True if successful.
        """
        if path.startswith("/memory/"):
            self._store_backend.write_file(path, content, user=user)
            return True
        else:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return True

    def list_memory_files(
        self,
        user: UserContext | None = None,
    ) -> list[dict[str, Any]]:
        """List all memory files for a user.

        Returns:
            List of dicts with key, content preview, updated_at.
        """
        items = self._store_backend.list_files(user=user)
        result = []
        for item in items:
            content = ""
            if isinstance(item.value, dict):
                content = item.value.get("content", "")
            elif isinstance(item.value, str):
                content = item.value
            result.append({
                "key": item.key,
                "content_preview": content[:200] if content else "",
                "updated_at": item.updated_at,
                "size": len(content),
            })
        return result


__all__ = [
    "CompositeBackend",
    "NamespaceFactory",
    "StoreBackend",
    "UserContext",
]