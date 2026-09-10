"""Memory middleware — injects memory files (AGENTS.md, MEMORY.md, USER.md, IDENTITY.md)
into the system prompt each turn with caching and progressive disclosure.

Inspired by DeepAgents' ``MemoryMiddleware`` and the orchestrator
memory files pattern (USER.md, MEMORY.md, IDENTITY.md, AGENTS.md).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.memory.backend import CompositeBackend, UserContext
from src.middleware.types import AgentMiddleware, MiddlewareConfig


# ── HTML comments stripping ─────────────────────────────────────────────

_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def strip_html_comments(text: str) -> str:
    """Remove HTML comments (``<!-- -->``) from text."""
    return _HTML_COMMENT_RE.sub("", text)


# ── Memory file descriptor ──────────────────────────────────────────────


@dataclass
class MemoryFile:
    """Descriptor for a single memory file."""

    filename: str
    """e.g. ``AGENTS.md``, ``MEMORY.md``, ``USER.md``, ``IDENTITY.md``."""
    virtual_path: str
    """Virtual path in the composite backend (e.g. ``/memory/AGENTS.md``)."""
    description: str
    """Description of what this file contains."""
    required: bool = False
    """If True, warn when missing."""
    cache_ttl: float = 300.0
    """Cache TTL in seconds (for prompt caching)."""
    progressive: bool = False
    """If True, load frontmatter first and defer body."""


# ── Memory middleware ───────────────────────────────────────────────────


DEFAULT_MEMORY_FILES = [
    MemoryFile(
        filename="AGENTS.md",
        virtual_path="/memory/AGENTS.md",
        description="Agent identity, instructions, and behavioral guidelines.",
        required=False,
        progressive=True,
    ),
    MemoryFile(
        filename="MEMORY.md",
        virtual_path="/memory/MEMORY.md",
        description="Conversation memory — facts, preferences, and context from past turns.",
        required=False,
        progressive=True,
    ),
    MemoryFile(
        filename="USER.md",
        virtual_path="/memory/USER.md",
        description="User profile — name, preferences, and personal context.",
        required=False,
    ),
    MemoryFile(
        filename="IDENTITY.md",
        virtual_path="/memory/IDENTITY.md",
        description="Agent identity and core behavioral rules.",
        required=False,
    ),
]

FRONTMATTER_LIMIT = 500
"""Number of characters for frontmatter-only loading."""


class MemoryMiddleware(AgentMiddleware):
    """Middleware that loads memory files and injects them into the system prompt.

    Memory files are read from a ``CompositeBackend`` (supporting both
    real filesystem and store-backed paths) and included in the
    ``system_prompt`` of every turn.

    Features:
    - Static injection: files loaded each turn
    - HTML comment stripping: ``<!-- -->`` auto-removed
    - Progressive disclosure: frontmatter-first, full body on demand
    - Cache control: TTL-based caching for prompt caching support
    """

    def __init__(
        self,
        backend: CompositeBackend | None = None,
        user_context: UserContext | None = None,
        memory_files: list[MemoryFile] | None = None,
    ) -> None:
        super().__init__()
        self._backend = backend or CompositeBackend()
        self._user = user_context
        self._memory_files = memory_files or DEFAULT_MEMORY_FILES
        self._cache: dict[str, tuple[str, float]] = {}
        """filename -> (content, timestamp)"""
        self._full_body_cache: dict[str, tuple[str, float]] = {}
        """filename -> (full_body, timestamp), populated on demand."""

    def set_user_context(self, user: UserContext) -> None:
        self._user = user

    async def before_agent(self, config: MiddlewareConfig) -> None:
        """Load memory files and inject into ``system_prompt``."""
        if not self._user:
            return

        memory_sections: list[str] = []
        expired_cache_keys: list[str] = []

        for mf in self._memory_files:
            content = self._load_with_cache(mf)

            if content is None:
                continue

            content = strip_html_comments(content)

            if mf.progressive and len(content) > FRONTMATTER_LIMIT:
                # Frontmatter-only for progressive files
                frontmatter = content[:FRONTMATTER_LIMIT]
                self._full_body_cache[mf.filename] = (content, time.time())
                memory_sections.append(
                    f"### {mf.filename} (frontmatter — request full for body)\n\n{frontmatter}"
                )
            else:
                memory_sections.append(f"### {mf.filename}\n\n{content}")

        # Clean expired caches
        for key in list(self._cache.keys()):
            _, ts = self._cache[key]
            ttl = 300.0
            if time.time() - ts > ttl:
                del self._cache[key]

        if not memory_sections:
            return

        memory_block = (
            "## Memory Files\n\n"
            + "\n\n---\n\n".join(memory_sections)
            + "\n\n---\n"
        )

        # Append to system prompt
        current_system = config.configurable.get("system_prompt", "")
        if current_system:
            config.configurable["system_prompt"] = current_system + "\n\n" + memory_block
        else:
            config.configurable["system_prompt"] = memory_block

    def get_full_body(self, filename: str) -> str | None:
        """Retrieve the full body for a progressively-disclosed file.

        Args:
            filename: e.g. ``AGENTS.md``, ``MEMORY.md``.

        Returns:
            Full body content or None.
        """
        entry = self._full_body_cache.get(filename)
        if entry:
            return entry[0]
        return None

    def _load_with_cache(self, mf: MemoryFile) -> str | None:
        """Load file content with cache check."""
        # Check cache
        cached = self._cache.get(mf.filename)
        if cached:
            content, ts = cached
            if time.time() - ts < mf.cache_ttl:
                return content

        # Load from backend
        result = self._backend.read_file(mf.virtual_path, user=self._user)
        if result is None:
            return None

        content = result.get("content", "")
        if not content:
            return None

        self._cache[mf.filename] = (content, time.time())
        return content

    def invalidate_cache(self, filename: str | None = None) -> None:
        """Invalidate the cache for a specific file or all files.

        Useful after writing new memory content.
        """
        if filename:
            self._cache.pop(filename, None)
            self._full_body_cache.pop(filename, None)
        else:
            self._cache.clear()
            self._full_body_cache.clear()

    async def after_agent(self, config: MiddlewareConfig) -> None:
        """Post-agent hook — currently a no-op for memory middleware."""
        pass


__all__ = [
    "DEFAULT_MEMORY_FILES",
    "MemoryFile",
    "MemoryMiddleware",
    "strip_html_comments",
]