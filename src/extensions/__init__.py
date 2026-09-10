"""Extensions system — plugins, hooks, and custom middleware registration."""

from src.extensions.plugin import (
    Plugin,
    PluginSpec,
    PluginRegistry,
    HookType,
    HookCallback,
)
from src.extensions.hooks import (
    LifecycleHook,
    HookRegistry,
    AgentLifecycle,
    ToolLifecycle,
)

__all__ = [
    "Plugin",
    "PluginSpec",
    "PluginRegistry",
    "HookType",
    "HookCallback",
    "LifecycleHook",
    "HookRegistry",
    "AgentLifecycle",
    "ToolLifecycle",
]