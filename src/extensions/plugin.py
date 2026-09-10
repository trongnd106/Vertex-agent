"""Plugin system — register and discover capabilities at runtime.

Allows external code to add new tools, middleware, hooks, and models
to the agent without modifying the core source.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import os
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class HookType(str, Enum):
    """Points in the agent lifecycle where plugins can hook in."""

    BEFORE_AGENT_TURN = "before_agent_turn"
    AFTER_AGENT_TURN = "after_agent_turn"
    BEFORE_TOOL_CALL = "before_tool_call"
    AFTER_TOOL_CALL = "after_tool_call"
    ON_ERROR = "on_error"
    ON_STARTUP = "on_startup"
    ON_SHUTDOWN = "on_shutdown"
    BEFORE_STREAM_CHUNK = "before_stream_chunk"
    AFTER_STREAM_CHUNK = "after_stream_chunk"


HookCallback = Callable[..., Any]


@dataclass
class PluginSpec:
    """Metadata about a plugin."""

    name: str
    """Unique plugin name."""

    version: str = "0.1.0"
    """Plugin version (semver)."""

    description: str = ""
    """Human-readable description."""

    author: str = ""
    """Plugin author."""

    dependencies: list[str] = field(default_factory=list)
    """Other plugin names this plugin depends on."""

    entry_point: str = ""
    """Python module path to load, e.g. 'my_plugin.main'."""


class Plugin(ABC):
    """Base class for all plugins.

    Subclass this and implement the hooks you need.
    """

    @abstractmethod
    def get_spec(self) -> PluginSpec:
        """Return the plugin's metadata."""
        ...

    def on_load(self, registry: PluginRegistry) -> None:
        """Called when the plugin is loaded into the registry.

        Override to register hooks, tools, or middleware.
        """
        ...

    def on_unload(self, registry: PluginRegistry) -> None:
        """Called when the plugin is unloaded.

        Override to clean up resources.
        """
        ...


class PluginRegistry:
    """Central registry for plugins, hooks, and extensions.

    Maintains a collection of loaded plugins, their hooks, and any
    custom tools/middleware they registered.
    """

    def __init__(self) -> None:
        self._plugins: dict[str, Plugin] = {}
        self._specs: dict[str, PluginSpec] = {}
        self._hooks: dict[HookType, list[tuple[str, HookCallback]]] = {
            ht: [] for ht in HookType
        }
        self._custom_tools: dict[str, type] = {}
        self._custom_middleware: dict[str, type] = {}
        self._custom_models: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Plugin lifecycle
    # ------------------------------------------------------------------

    def register(self, plugin: Plugin) -> None:
        """Register and load a plugin.

        Calls ``on_load()`` on the plugin so it can register hooks.
        """
        spec = plugin.get_spec()
        if spec.name in self._plugins:
            logger.warning("Plugin %r already registered; reloading", spec.name)

        # Load dependencies first
        for dep_name in spec.dependencies:
            if dep_name not in self._plugins:
                raise RuntimeError(
                    f"Plugin {spec.name} requires {dep_name} which is not loaded"
                )

        self._plugins[spec.name] = plugin
        self._specs[spec.name] = spec
        plugin.on_load(self)

        logger.info("Plugin loaded: %s v%s", spec.name, spec.version)

    def unregister(self, name: str) -> None:
        """Unload a plugin."""
        plugin = self._plugins.get(name)
        if plugin is None:
            raise KeyError(f"Plugin {name!r} is not registered")

        # Check for dependents
        for other_name, other_spec in self._specs.items():
            if name in other_spec.dependencies:
                logger.warning(
                    "Plugin %s depends on %s; unloading anyway", other_name, name
                )

        plugin.on_unload(self)

        # Remove hooks registered by this plugin
        for hook_type in HookType:
            self._hooks[hook_type] = [
                (pn, cb) for pn, cb in self._hooks[hook_type] if pn != name
            ]

        del self._plugins[name]
        del self._specs[name]
        logger.info("Plugin unloaded: %s", name)

    def load_from_module(self, module_path: str, class_name: str) -> None:
        """Dynamically load a plugin from a Python module path.

        Example::
            registry.load_from_module("my_plugin.main", "MyPlugin")
        """
        try:
            module = importlib.import_module(module_path)
            plugin_class = getattr(module, class_name)
            if not inspect.isclass(plugin_class) or not issubclass(plugin_class, Plugin):
                raise TypeError(
                    f"{class_name} must be a subclass of Plugin"
                )
            plugin = plugin_class()
            self.register(plugin)
        except Exception as exc:
            logger.error("Failed to load plugin from %s.%s: %s", module_path, class_name, exc)
            raise

    def load_from_directory(self, directory: str) -> list[str]:
        """Discover and load all plugins in a directory.

        Looks for modules matching ``*_plugin.py``.
        Returns the list of loaded plugin names.
        """
        loaded: list[str] = []
        if not os.path.isdir(directory):
            logger.warning("Plugin directory not found: %s", directory)
            return loaded

        sys.path.insert(0, directory)
        try:
            for filename in sorted(os.listdir(directory)):
                if filename.endswith("_plugin.py"):
                    module_name = filename[:-3]
                    try:
                        module = importlib.import_module(module_name)
                        for name, obj in inspect.getmembers(module):
                            if (inspect.isclass(obj)
                                    and issubclass(obj, Plugin)
                                    and obj is not Plugin):
                                plugin = obj()
                                self.register(plugin)
                                loaded.append(plugin.get_spec().name)
                    except Exception as exc:
                        logger.error("Failed to load plugin module %s: %s", filename, exc)
        finally:
            sys.path.pop(0)

        return loaded

    # ------------------------------------------------------------------
    # Hook management
    # ------------------------------------------------------------------

    def register_hook(self, hook_type: HookType, callback: HookCallback, plugin_name: str = "") -> None:
        """Register a callback for a lifecycle hook."""
        self._hooks[hook_type].append((plugin_name, callback))

    def unregister_hook(self, hook_type: HookType, callback: HookCallback) -> None:
        """Remove a specific hook callback."""
        self._hooks[hook_type] = [
            (pn, cb) for pn, cb in self._hooks[hook_type] if cb is not callback
        ]

    def run_hooks(self, hook_type: HookType, *args: Any, **kwargs: Any) -> list[Any]:
        """Execute all callbacks for a hook type and return their results."""
        results: list[Any] = []
        for plugin_name, callback in self._hooks[hook_type]:
            try:
                result = callback(*args, **kwargs)
                results.append(result)
            except Exception as exc:
                logger.error(
                    "Hook %s callback from plugin %s failed: %s",
                    hook_type.value,
                    plugin_name,
                    exc,
                )
        return results

    # ------------------------------------------------------------------
    # Custom tool / middleware / model registration
    # ------------------------------------------------------------------

    def register_tool(self, name: str, tool_class: type) -> None:
        """Register a custom tool class."""
        self._custom_tools[name] = tool_class

    def get_tools(self) -> dict[str, type]:
        """Get all registered custom tools."""
        return dict(self._custom_tools)

    def register_middleware(self, name: str, middleware_class: type) -> None:
        """Register a custom middleware class."""
        self._custom_middleware[name] = middleware_class

    def get_middleware(self) -> dict[str, type]:
        """Get all registered custom middleware."""
        return dict(self._custom_middleware)

    def register_model(self, name: str, model_config: Any) -> None:
        """Register a custom model configuration."""
        self._custom_models[name] = model_config

    def get_models(self) -> dict[str, Any]:
        """Get all registered custom models."""
        return dict(self._custom_models)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_plugin(self, name: str) -> Plugin | None:
        """Get a loaded plugin by name."""
        return self._plugins.get(name)

    def list_plugins(self) -> list[PluginSpec]:
        """List all loaded plugin specs."""
        return list(self._specs.values())

    def is_loaded(self, name: str) -> bool:
        """Check if a plugin is loaded."""
        return name in self._plugins