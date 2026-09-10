"""Tests for Extensions system (Task 10.5) — plugins and hooks."""

from __future__ import annotations

import pytest

from src.extensions import (
    AgentLifecycle,
    HookCallback,
    HookRegistry,
    HookType,
    LifecycleHook,
    Plugin,
    PluginRegistry,
    PluginSpec,
    ToolLifecycle,
)


# ------------------------------------------------------------------
# Plugin tests
# ------------------------------------------------------------------

class TestPluginSpec:
    def test_defaults(self) -> None:
        spec = PluginSpec(name="test-plugin")
        assert spec.name == "test-plugin"
        assert spec.version == "0.1.0"
        assert spec.description == ""
        assert spec.author == ""
        assert spec.dependencies == []
        assert spec.entry_point == ""

    def test_full_spec(self) -> None:
        spec = PluginSpec(
            name="my-plugin",
            version="1.0.0",
            description="A test plugin",
            author="Test Author",
            dependencies=["base-plugin"],
            entry_point="my_plugin.main",
        )
        assert spec.version == "1.0.0"
        assert "base-plugin" in spec.dependencies


class TestPlugin(Plugin):
    """A simple test plugin."""

    def __init__(self) -> None:
        super().__init__()
        self.loaded = False
        self.unloaded = False

    def get_spec(self) -> PluginSpec:
        return PluginSpec(
            name="test-plugin",
            version="0.1.0",
            description="A test plugin",
        )

    def on_load(self, registry: PluginRegistry) -> None:
        self.loaded = True
        registry.register_hook(HookType.AFTER_AGENT_TURN, lambda: None, plugin_name="test-plugin")

    def on_unload(self, registry: PluginRegistry) -> None:
        self.unloaded = True


class TestPluginWithDeps(Plugin):
    def get_spec(self) -> PluginSpec:
        return PluginSpec(
            name="dependent-plugin",
            dependencies=["test-plugin"],
        )

    def on_load(self, registry: PluginRegistry) -> None:
        pass

    def on_unload(self, registry: PluginRegistry) -> None:
        pass


class TestPluginRegistry:
    def test_register_and_list(self) -> None:
        registry = PluginRegistry()
        plugin = TestPlugin()
        registry.register(plugin)
        assert registry.is_loaded("test-plugin")
        specs = registry.list_plugins()
        assert len(specs) == 1
        assert specs[0].name == "test-plugin"

    def test_register_calls_on_load(self) -> None:
        registry = PluginRegistry()
        plugin = TestPlugin()
        registry.register(plugin)
        assert plugin.loaded

    def test_get_plugin(self) -> None:
        registry = PluginRegistry()
        plugin = TestPlugin()
        registry.register(plugin)
        assert registry.get_plugin("test-plugin") is plugin
        assert registry.get_plugin("nonexistent") is None

    def test_unregister(self) -> None:
        registry = PluginRegistry()
        plugin = TestPlugin()
        registry.register(plugin)
        registry.unregister("test-plugin")
        assert not registry.is_loaded("test-plugin")
        assert plugin.unloaded

    def test_unregister_nonexistent(self) -> None:
        registry = PluginRegistry()
        with pytest.raises(KeyError):
            registry.unregister("nonexistent")

    def test_dependency_check_on_register(self) -> None:
        registry = PluginRegistry()
        dep_plugin = TestPluginWithDeps()
        with pytest.raises(RuntimeError, match="requires.*test-plugin"):
            registry.register(dep_plugin)

        # With dependency loaded first, it should work
        registry.register(TestPlugin())
        dep_plugin2 = TestPluginWithDeps()
        registry.register(dep_plugin2)  # Should not raise
        assert registry.is_loaded("dependent-plugin")

    def test_hook_registration_and_execution(self) -> None:
        registry = PluginRegistry()
        results: list[str] = []

        def hook1() -> None:
            results.append("hook1")

        def hook2() -> None:
            results.append("hook2")

        registry.register_hook(HookType.AFTER_AGENT_TURN, hook1, "p1")
        registry.register_hook(HookType.AFTER_AGENT_TURN, hook2, "p2")

        registry.run_hooks(HookType.AFTER_AGENT_TURN)
        assert "hook1" in results
        assert "hook2" in results

    def test_hook_unregister(self) -> None:
        registry = PluginRegistry()

        def hook() -> None:
            pass

        registry.register_hook(HookType.BEFORE_AGENT_TURN, hook, "p1")
        registry.unregister_hook(HookType.BEFORE_AGENT_TURN, hook)
        results = registry.run_hooks(HookType.BEFORE_AGENT_TURN)
        assert len(results) == 0

    def test_hook_exception_does_not_block(self) -> None:
        registry = PluginRegistry()
        results: list[str] = []

        def failing_hook() -> None:
            raise ValueError("Oops")

        def good_hook() -> str:
            results.append("ran")
            return "ok"

        registry.register_hook(HookType.ON_ERROR, failing_hook, "p1")
        registry.register_hook(HookType.ON_ERROR, good_hook, "p2")

        # Should not raise; failing hook is caught and logged
        outs = registry.run_hooks(HookType.ON_ERROR)
        assert "ran" in results
        assert "ok" in outs  # The good hook should have returned 'ok'

    def test_all_hook_types_have_empty_lists(self) -> None:
        registry = PluginRegistry()
        for ht in HookType:
            assert registry._hooks[ht] == []

    def test_register_tool_and_middleware(self) -> None:
        registry = PluginRegistry()
        registry.register_tool("my_tool", str)
        registry.register_middleware("my_middleware", int)
        assert "my_tool" in registry.get_tools()
        assert "my_middleware" in registry.get_middleware()

    def test_register_model(self) -> None:
        registry = PluginRegistry()
        registry.register_model("gpt-4", {"provider": "openai"})
        models = registry.get_models()
        assert "gpt-4" in models
        assert models["gpt-4"]["provider"] == "openai"

    def test_load_from_module_invalid(self) -> None:
        registry = PluginRegistry()
        with pytest.raises((ImportError, AttributeError, TypeError)):
            registry.load_from_module("nonexistent_module", "Plugin")

    def test_load_from_directory_nonexistent(self) -> None:
        registry = PluginRegistry()
        loaded = registry.load_from_directory("/nonexistent/plugins")
        assert loaded == []


# ------------------------------------------------------------------
# HookRegistry tests
# ------------------------------------------------------------------

class TestHookRegistry:
    @pytest.mark.asyncio
    async def test_register_and_emit(self) -> None:
        registry = HookRegistry()
        results: list[str] = []

        registry.on("before_turn", lambda: results.append("ran"))
        await registry.emit("before_turn")
        assert "ran" in results

    @pytest.mark.asyncio
    async def test_on_decorator(self) -> None:
        registry = HookRegistry()
        results: list[str] = []

        @registry.on("after_turn")
        def handler() -> None:
            results.append("decorated")

        await registry.emit("after_turn")
        assert "decorated" in results

    @pytest.mark.asyncio
    async def test_emit_sync(self) -> None:
        registry = HookRegistry()
        results: list[str] = []

        registry.on("before_tool", lambda: results.append("sync_hook"))
        registry.emit_sync("before_tool")
        assert "sync_hook" in results

    @pytest.mark.asyncio
    async def test_off(self) -> None:
        registry = HookRegistry()

        def handler() -> str:
            return "removed"

        registry.on("on_error", handler)
        registry.off("on_error", handler)
        results = await registry.emit("on_error")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_once_hook(self) -> None:
        registry = HookRegistry()
        call_count = 0

        def handler() -> None:
            nonlocal call_count
            call_count += 1

        registry.on("before_turn", handler, once=True)
        await registry.emit("before_turn")
        await registry.emit("before_turn")
        assert call_count == 1  # Should only fire once

    @pytest.mark.asyncio
    async def test_handler_exception_does_not_block(self) -> None:
        registry = HookRegistry()
        results: list[str] = []

        def failing() -> None:
            raise ValueError("fail")

        def good() -> None:
            results.append("ok")

        registry.on("on_error", failing)
        registry.on("on_error", good)

        await registry.emit("on_error")
        assert "ok" in results

    def test_priority_order(self) -> None:
        registry = HookRegistry()
        order: list[int] = []

        registry.on("before_turn", lambda: order.append(2), name="low", priority=0)
        registry.on("before_turn", lambda: order.append(1), name="high", priority=10)

        registry.emit_sync("before_turn")
        assert order == [1, 2]

    def test_list_hooks(self) -> None:
        registry = HookRegistry()
        registry.on("before_turn", lambda: None, name="h1")
        registry.on("after_turn", lambda: None, name="h2")

        hooks = registry.list_hooks()
        assert "before_turn" in hooks
        assert "after_turn" in hooks

        filtered = registry.list_hooks("before_turn")
        assert "before_turn" in filtered
        assert "after_turn" not in filtered

    def test_handler_count(self) -> None:
        registry = HookRegistry()
        registry.on("before_turn", lambda: None)
        registry.on("before_turn", lambda: None)
        registry.on("after_turn", lambda: None)

        assert registry.handler_count("before_turn") == 2
        assert registry.handler_count() == 3

    def test_clear(self) -> None:
        registry = HookRegistry()
        registry.on("before_turn", lambda: None)
        registry.clear()
        assert registry.handler_count() == 0


# ------------------------------------------------------------------
# Lifecycle / AgentLifecycle / ToolLifecycle enum tests
# ------------------------------------------------------------------

class TestLifecycleEnums:
    def test_agent_lifecycle_values(self) -> None:
        values = [e.value for e in AgentLifecycle]
        assert "before_turn" in values
        assert "after_turn" in values
        assert "before_tool" in values
        assert "after_tool" in values
        assert "before_stream" in values
        assert "after_stream" in values
        assert "on_error" in values

    def test_tool_lifecycle_values(self) -> None:
        values = [e.value for e in ToolLifecycle]
        assert "before_call" in values
        assert "after_call" in values
        assert "on_error" in values

    def test_hook_type_values(self) -> None:
        values = [e.value for e in HookType]
        assert "before_agent_turn" in values
        assert "after_agent_turn" in values
        assert "before_tool_call" in values
        assert "on_startup" in values
        assert "on_shutdown" in values

    def test_lifecycle_hook_dataclass(self) -> None:
        hook = LifecycleHook(
            event="before_turn",
            handler=lambda: None,
            name="test",
            priority=5,
            once=True,
        )
        assert hook.event == "before_turn"
        assert hook.priority == 5
        assert hook.once