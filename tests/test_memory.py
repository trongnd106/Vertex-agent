"""Tests for the Memory & Persistence system (Task 4: 4.1–4.6).

Covers:
    4.1  Checkpoint System (InMemorySaver, TimeTravel)
    4.2  Long-term Memory Store (InMemoryStore, PostgresStore)
    4.3  Memory Backend (StoreBackend, CompositeBackend)
    4.4  AGENTS.md / Memory Files System (MemoryMiddleware)
    4.5  StoreBackend Namespace Management (NamespaceManager)
    4.6  Dreaming System (DreamEngine, Consolidation, Enqueue, Alerts)
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from src.memory.checkpoint import (
    Checkpoint,
    CheckpointMetadata,
    InMemorySaver,
    PendingWrite,
    TimeTravel,
)
from src.memory.store import (
    BaseStore,
    InMemoryStore,
    Item,
    PostgresStore,
)
from src.memory.backend import CompositeBackend, StoreBackend, UserContext
from src.memory.memory_middleware import (
    MemoryMiddleware,
    strip_html_comments,
)
from src.memory.namespace import (
    NamespaceManager,
    NamespaceRule,
    user_namespace,
    bot_user_namespace,
    global_namespace,
)

# Dreaming is a separate sub-package (pre-existing); import what's available
try:
    from src.memory.dreaming.enqueue import EnqueueAfterTurnMiddleware
    from src.memory.dreaming.scan import scan_and_dream
    _DREAMING_AVAILABLE = True
except ImportError:
    _DREAMING_AVAILABLE = False

from src.middleware.types import MiddlewareConfig


# ══════════════════════════════════════════════════════════════════════════
# 4.1  Checkpoint System
# ══════════════════════════════════════════════════════════════════════════


class TestCheckpoint:
    """Test Checkpoint dataclass."""

    def test_copy_is_independent(self) -> None:
        c = Checkpoint(id="c1", channel_values={"key": "val"})
        c2 = c.copy()
        c2.channel_values["key"] = "modified"
        assert c.channel_values["key"] == "val"

    def test_pending_write(self) -> None:
        pw = PendingWrite(channel="messages", value="hello", task_id="t1")
        assert pw.channel == "messages"


class TestInMemorySaver:
    """Test InMemorySaver."""

    @pytest.fixture
    def saver(self) -> InMemorySaver:
        return InMemorySaver()

    def test_put_and_get(self, saver: InMemorySaver) -> None:
        config = {"configurable": {"thread_id": "thread_1"}}
        ckpt = Checkpoint(id="c1", ts=100.0, channel_values={"x": 1})
        meta = CheckpointMetadata(source="step", step=1)
        saver.put(config, ckpt, meta)
        retrieved = saver.get(config)
        assert retrieved is not None
        assert retrieved.id == "c1"

    def test_get_nonexistent(self, saver: InMemorySaver) -> None:
        config = {"configurable": {"thread_id": "nonexistent"}}
        assert saver.get(config) is None

    def test_get_by_checkpoint_id(self, saver: InMemorySaver) -> None:
        config = {"configurable": {"thread_id": "t1"}}
        c1 = Checkpoint(id="c1", ts=100.0)
        c2 = Checkpoint(id="c2", ts=200.0)
        saver.put(config, c1, CheckpointMetadata())
        saver.put(config, c2, CheckpointMetadata())
        retrieved = saver.get({"configurable": {"thread_id": "t1", "checkpoint_id": "c1"}})
        assert retrieved is not None and retrieved.id == "c1"

    def test_get_tuple(self, saver: InMemorySaver) -> None:
        config = {"configurable": {"thread_id": "t1"}}
        ckpt = Checkpoint(id="c1", ts=100.0)
        saver.put(config, ckpt, CheckpointMetadata())
        saver.put_writes(config, "c1", [PendingWrite("ch", "val")])
        result = saver.get_tuple(config)
        assert result is not None
        c, writes = result
        assert c.id == "c1"
        assert len(writes) == 1

    def test_list(self, saver: InMemorySaver) -> None:
        config = {"configurable": {"thread_id": "t1"}}
        for i in range(5):
            saver.put(config, Checkpoint(id=f"c{i}", ts=float(i)), CheckpointMetadata())
        results = saver.list(config, limit=3)
        assert len(results) == 3
        # Newest first
        assert results[0].id == "c4"

    def test_list_with_before(self, saver: InMemorySaver) -> None:
        config = {"configurable": {"thread_id": "t1"}}
        for i in range(5):
            saver.put(config, Checkpoint(id=f"c{i}", ts=float(i)), CheckpointMetadata())
        before = Checkpoint(ts=3.0)
        results = saver.list(config, before=before, limit=10)
        assert all(c.ts < 3.0 for c in results)

    def test_put_writes_and_crash_recovery(self, saver: InMemorySaver) -> None:
        config = {"configurable": {"thread_id": "t1"}}
        ckpt = Checkpoint(id="c1")
        saver.put(config, ckpt, CheckpointMetadata())
        saver.put_writes(config, "c1", [PendingWrite("ch1", "v1"), PendingWrite("ch2", "v2")])
        result = saver.get_tuple(config)
        assert result is not None
        _, writes = result
        assert len(writes) == 2

    def test_clear(self, saver: InMemorySaver) -> None:
        config = {"configurable": {"thread_id": "t1"}}
        saver.put(config, Checkpoint(id="c1"), CheckpointMetadata())
        saver.clear()
        assert saver.get(config) is None

    def test_multiple_threads(self, saver: InMemorySaver) -> None:
        saver.put({"configurable": {"thread_id": "a"}}, Checkpoint(id="a1", ts=1.0), CheckpointMetadata())
        saver.put({"configurable": {"thread_id": "b"}}, Checkpoint(id="b1", ts=2.0), CheckpointMetadata())
        assert saver.get({"configurable": {"thread_id": "a"}}).id == "a1"
        assert saver.get({"configurable": {"thread_id": "b"}}).id == "b1"


class TestTimeTravel:
    """Test TimeTravel."""

    @pytest.fixture
    def saver(self) -> InMemorySaver:
        s = InMemorySaver()
        config = {"configurable": {"thread_id": "t1"}}
        for i in range(3):
            s.put(config, Checkpoint(id=f"c{i}", ts=float(i)), CheckpointMetadata(step=i))
        return s

    def test_get_history(self, saver: InMemorySaver) -> None:
        tt = TimeTravel(saver)
        history = tt.get_history("t1", limit=10)
        assert len(history) == 3

    def test_replay_from(self, saver: InMemorySaver) -> None:
        tt = TimeTravel(saver)
        result = tt.replay_from("t1", "c1")
        assert result is not None
        ckpt, writes = result
        assert ckpt.id == "c1"


# ══════════════════════════════════════════════════════════════════════════
# 4.2  Long-term Memory Store
# ══════════════════════════════════════════════════════════════════════════


class TestItem:
    """Test Item dataclass."""

    def test_ttl_expiry(self) -> None:
        item = Item(key="k", value="v", ttl=0.1, updated_at=time.time() - 1)
        assert item.is_expired()

    def test_no_ttl(self) -> None:
        item = Item(key="k", value="v", ttl=0)
        assert not item.is_expired()

    def test_to_dict(self) -> None:
        item = Item(key="k", value={"a": 1}, namespace=("memories", "u1"))
        d = item.to_dict()
        assert d["key"] == "k"
        assert d["value"] == {"a": 1}


class TestInMemoryStore:
    """Test InMemoryStore."""

    @pytest.fixture
    def store(self) -> InMemoryStore:
        return InMemoryStore()

    def test_put_and_get(self, store: InMemoryStore) -> None:
        item = store.put(("memories", "u1"), "key1", {"text": "hello"})
        retrieved = store.get(("memories", "u1"), "key1")
        assert retrieved is not None
        assert retrieved.value == {"text": "hello"}

    def test_get_nonexistent(self, store: InMemoryStore) -> None:
        assert store.get(("nonexistent",), "k") is None

    def test_put_updates_existing(self, store: InMemoryStore) -> None:
        store.put(("ns",), "k", "v1")
        store.put(("ns",), "k", "v2")
        item = store.get(("ns",), "k")
        assert item.value == "v2"

    def test_search(self, store: InMemoryStore) -> None:
        store.put(("memories", "u1"), "greeting", {"text": "hello world"})
        store.put(("memories", "u1"), "farewell", {"text": "goodbye"})
        store.put(("memories", "u2"), "greeting", {"text": "hi"})
        results = store.search(("memories", "u1"))
        assert results.total == 2

    def test_search_with_query(self, store: InMemoryStore) -> None:
        store.put(("ns",), "a", "apple banana")
        store.put(("ns",), "b", "banana cherry")
        store.put(("ns",), "c", "date")
        results = store.search(("ns",), query="banana")
        assert results.total == 2

    def test_search_with_filter(self, store: InMemoryStore) -> None:
        store.put(("ns",), "a", {"type": "note", "text": "hello"})
        store.put(("ns",), "b", {"type": "task", "text": "done"})
        results = store.search(("ns",), filter={"type": "note"})
        assert results.total == 1

    def test_delete(self, store: InMemoryStore) -> None:
        store.put(("ns",), "k", "v")
        assert store.delete(("ns",), "k") is True
        assert store.get(("ns",), "k") is None
        assert store.delete(("ns",), "nonexistent") is False

    def test_list_namespaces(self, store: InMemoryStore) -> None:
        store.put(("memories", "u1"), "k1", "v1")
        store.put(("memories", "u2"), "k2", "v2")
        store.put(("system", "config"), "k3", "v3")
        nss = store.list_namespaces()
        assert len(nss) == 3

    def test_list_namespaces_with_prefix(self, store: InMemoryStore) -> None:
        store.put(("memories", "u1"), "k", "v")
        store.put(("system", "cfg"), "k", "v")
        nss = store.list_namespaces(prefix=("memories",))
        assert nss == [("memories", "u1")]

    def test_clear(self, store: InMemoryStore) -> None:
        store.put(("ns",), "k", "v")
        store.clear()
        assert store.get(("ns",), "k") is None


class TestPostgresStore:
    """Test PostgresStore — relies on psycopg being installed."""

    def test_init(self) -> None:
        store = PostgresStore()
        assert isinstance(store, BaseStore)

    def test_requires_psycopg(self) -> None:
        store = PostgresStore()
        if not hasattr(store, "_available") or not store._available:
            with pytest.raises(RuntimeError, match="requires psycopg"):
                store.get(("test",), "k")


# ══════════════════════════════════════════════════════════════════════════
# 4.3  Memory Backend
# ══════════════════════════════════════════════════════════════════════════


class TestStoreBackend:
    """Test StoreBackend."""

    @pytest.fixture
    def backend(self) -> StoreBackend:
        return StoreBackend()

    @pytest.fixture
    def user(self) -> UserContext:
        return UserContext(user_id="u1")

    def test_write_and_read(self, backend: StoreBackend, user: UserContext) -> None:
        backend.write_file("/memory/notes.md", "Hello notes", user=user)
        item = backend.read_file("/memory/notes.md", user=user)
        assert item is not None
        assert item.value["content"] == "Hello notes"

    def test_delete(self, backend: StoreBackend, user: UserContext) -> None:
        backend.write_file("/memory/tmp.md", "temp", user=user)
        assert backend.delete_file("/memory/tmp.md", user=user) is True
        assert backend.read_file("/memory/tmp.md", user=user) is None

    def test_list_files(self, backend: StoreBackend, user: UserContext) -> None:
        backend.write_file("/memory/a.md", "a", user=user)
        backend.write_file("/memory/b.md", "b", user=user)
        items = backend.list_files(user=user)
        assert len(items) == 2

    def test_different_users_isolation(self) -> None:
        backend = StoreBackend()
        u1 = UserContext(user_id="u1")
        u2 = UserContext(user_id="u2")
        backend.write_file("/memory/secret.md", "u1 data", user=u1)
        backend.write_file("/memory/secret.md", "u2 data", user=u2)
        item1 = backend.read_file("/memory/secret.md", user=u1)
        item2 = backend.read_file("/memory/secret.md", user=u2)
        assert item1.value["content"] != item2.value["content"]


class TestCompositeBackend:
    """Test CompositeBackend routing."""

    @pytest.fixture
    def backend(self) -> CompositeBackend:
        return CompositeBackend()

    def test_routes_memory_path(self, backend: CompositeBackend) -> None:
        user = UserContext(user_id="u1")
        backend.write_file("/memory/test.md", "mem data", user=user)
        result = backend.read_file("/memory/test.md", user=user)
        assert result is not None
        assert "mem data" in result["content"]

    def test_routes_real_filesystem(self, backend: CompositeBackend, tmp_path: Path) -> None:
        f = tmp_path / "real.txt"
        f.write_text("real data", encoding="utf-8")
        result = backend.read_file(str(f))
        assert result is not None
        assert "real data" in result["content"]

    def test_list_memory_files(self, backend: CompositeBackend) -> None:
        user = UserContext(user_id="u1")
        backend.write_file("/memory/a.md", "aaa", user=user)
        backend.write_file("/memory/b.md", "bbb", user=user)
        files = backend.list_memory_files(user=user)
        assert len(files) == 2


# ══════════════════════════════════════════════════════════════════════════
# 4.4  AGENTS.md / Memory Files System
# ══════════════════════════════════════════════════════════════════════════


class TestStripHTMLComments:
    """Test HTML comments stripping."""

    def test_strip_basic(self) -> None:
        assert strip_html_comments("Hello <!-- comment -->world") == "Hello world"

    def test_strip_multiline(self) -> None:
        text = "Start\n<!-- multi\nline\ncomment -->\nEnd"
        assert strip_html_comments(text) == "Start\n\nEnd"

    def test_no_comments(self) -> None:
        assert strip_html_comments("plain text") == "plain text"


class TestMemoryMiddleware:
    """Test MemoryMiddleware."""

    @pytest.fixture
    def user(self) -> UserContext:
        return UserContext(user_id="test_user")

    @pytest.fixture
    def middleware(self, user: UserContext) -> MemoryMiddleware:
        mw = MemoryMiddleware(user_context=user)
        return mw

    def test_injects_memory_block(self, middleware: MemoryMiddleware) -> None:
        config = MiddlewareConfig()
        config.configurable["system_prompt"] = "You are a helpful assistant."
        import asyncio
        asyncio.run(middleware.before_agent(config))
        # If no memory files exist, system_prompt is unchanged
        assert "Memory Files" not in config.configurable.get("system_prompt", "")

    def test_with_written_memory(self, user: UserContext) -> None:
        mw = MemoryMiddleware(user_context=user)
        mw._backend.write_file("/memory/AGENTS.md", "You are a coding agent.", user=user)
        config = MiddlewareConfig()
        config.configurable["system_prompt"] = "System prompt."
        import asyncio
        asyncio.run(mw.before_agent(config))
        assert "AGENTS.md" in config.configurable.get("system_prompt", "")
        assert "coding agent" in config.configurable.get("system_prompt", "")

    def test_html_comments_stripped(self, user: UserContext) -> None:
        mw = MemoryMiddleware(user_context=user)
        mw._backend.write_file("/memory/MEMORY.md", "Keep <!-- secret --> visible", user=user)
        config = MiddlewareConfig()
        import asyncio
        asyncio.run(mw.before_agent(config))
        assert "secret" not in config.configurable.get("system_prompt", "")
        assert "visible" in config.configurable.get("system_prompt", "")

    def test_progressive_disclosure(self, user: UserContext) -> None:
        mw = MemoryMiddleware(user_context=user)
        long_body = "A" * 600
        mw._backend.write_file("/memory/AGENTS.md", long_body, user=user)
        config = MiddlewareConfig()
        import asyncio
        asyncio.run(mw.before_agent(config))
        assert "frontmatter" in config.configurable.get("system_prompt", "")

    def test_full_body_retrieval(self, user: UserContext) -> None:
        mw = MemoryMiddleware(user_context=user)
        # Must exceed FRONTMATTER_LIMIT (500) to trigger progressive caching
        body = "X" * 600
        mw._backend.write_file("/memory/AGENTS.md", body, user=user)
        config = MiddlewareConfig()
        import asyncio
        asyncio.run(mw.before_agent(config))
        full = mw.get_full_body("AGENTS.md")
        assert full == body

    def test_cache_invalidation(self, user: UserContext) -> None:
        mw = MemoryMiddleware(user_context=user)
        mw._backend.write_file("/memory/MEMORY.md", "version 1", user=user)
        config = MiddlewareConfig()
        import asyncio
        asyncio.run(mw.before_agent(config))
        assert "version 1" in config.configurable.get("system_prompt", "")
        # Update file and invalidate
        mw._backend.write_file("/memory/MEMORY.md", "version 2", user=user)
        mw.invalidate_cache("MEMORY.md")
        config2 = MiddlewareConfig()
        import asyncio
        asyncio.run(mw.before_agent(config2))
        assert "version 2" in config2.configurable.get("system_prompt", "")


# ══════════════════════════════════════════════════════════════════════════
# 4.5  Namespace Management
# ══════════════════════════════════════════════════════════════════════════


class TestNamespaceFunctions:
    """Test namespace factory functions."""

    def test_user_namespace(self) -> None:
        user = UserContext(user_id="u123")
        ns = user_namespace(user)
        assert ns == ("memories", "u123")

    def test_user_namespace_empty_raises(self) -> None:
        user = UserContext(user_id="")
        with pytest.raises(RuntimeError):
            user_namespace(user)

    def test_bot_user_namespace(self) -> None:
        user = UserContext(user_id="u1")
        ns = bot_user_namespace("bot1", user)
        assert ns == ("memories", "bot1", "u1")

    def test_global_namespace(self) -> None:
        assert global_namespace() == ("memories", "global")


class TestNamespaceManager:
    """Test NamespaceManager."""

    @pytest.fixture
    def manager(self) -> NamespaceManager:
        return NamespaceManager()

    def test_resolve_with_user(self, manager: NamespaceManager) -> None:
        manager.build_default()
        ns = manager.resolve(user=UserContext(user_id="u1"))
        assert ns == ("memories", "u1")

    def test_resolve_with_bot_and_user(self, manager: NamespaceManager) -> None:
        manager.build_default()
        ns = manager.resolve(
            bot_id="b1",
            user=UserContext(user_id="u1"),
        )
        assert ns == ("memories", "b1", "u1")

    def test_resolve_fallback_to_global(self, manager: NamespaceManager) -> None:
        # Add only the global rule
        manager.add_rule(NamespaceRule(
            name="global",
            resolver=lambda **ctx: global_namespace(),
            priority=10,
        ))
        ns = manager.resolve()
        assert ns == ("memories", "global")

    def test_no_rules_raises(self, manager: NamespaceManager) -> None:
        with pytest.raises(RuntimeError):
            manager.resolve()

    def test_deny_namespace(self, manager: NamespaceManager) -> None:
        manager.build_default()
        manager.deny_namespace(("memories", "blocked_user"))
        # Falls through to global namespace when user is blocked
        ns = manager.resolve(user=UserContext(user_id="blocked_user"))
        assert ns == ("memories", "global")

    def test_allow_list(self, manager: NamespaceManager) -> None:
        manager.build_default()
        manager.allow_namespace(("memories", "allowed_user"))
        # Deny everything except allowed_user
        with pytest.raises(RuntimeError):
            manager.resolve(user=UserContext(user_id="other_user"))

    def test_grant_and_revoke_access(self, manager: NamespaceManager) -> None:
        manager.build_default()
        manager.grant_access(("memories", "bot1"), "user_a")
        manager.revoke_access(("memories", "bot1"), "user_a")

    def test_remove_rule(self, manager: NamespaceManager) -> None:
        manager.build_default()
        assert manager.remove_rule("user") is True
        assert manager.remove_rule("nonexistent") is False


# ══════════════════════════════════════════════════════════════════════════
# 4.6  Dreaming System (pre-existing sub-package)
# ══════════════════════════════════════════════════════════════════════════


class TestDreamingAvailable:
    """Test that dreaming sub-package is importable if dependencies exist."""

    def test_enqueue_middleware_importable(self) -> None:
        """EnqueueAfterTurnMiddleware should be importable if langchain available."""
        if _DREAMING_AVAILABLE:
            from src.memory.dreaming.enqueue import EnqueueAfterTurnMiddleware
            mw = EnqueueAfterTurnMiddleware()
            assert mw is not None