"""Lifecycle hooks — pre/post hooks for agent turns and tool calls.

Provides a lightweight hook system independent of the plugin system,
so middleware and other components can subscribe to lifecycle events.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class AgentLifecycle(str, Enum):
    """Agent turn lifecycle phases."""

    BEFORE_TURN = "before_turn"
    AFTER_TURN = "after_turn"
    BEFORE_TOOL = "before_tool"
    AFTER_TOOL = "after_tool"
    BEFORE_STREAM = "before_stream"
    AFTER_STREAM = "after_stream"
    ON_ERROR = "on_error"


class ToolLifecycle(str, Enum):
    """Tool call lifecycle phases."""

    BEFORE_CALL = "before_call"
    AFTER_CALL = "after_call"
    ON_ERROR = "on_error"


LifecycleEvent = str  # One of AgentLifecycle or ToolLifecycle values
HookHandler = Callable[..., Any]


@dataclass
class LifecycleHook:
    """A registered lifecycle hook."""

    event: LifecycleEvent
    handler: HookHandler
    name: str = ""
    priority: int = 0
    """Higher priority hooks run first."""

    once: bool = False
    """If True, the hook is removed after its first execution."""

    def __hash__(self) -> int:
        return id(self)


class HookRegistry:
    """Thread-safe registry for lifecycle hooks.

    Allows any component to subscribe to agent and tool lifecycle events
    without direct coupling.
    """

    def __init__(self) -> None:
        self._hooks: dict[LifecycleEvent, list[LifecycleHook]] = {}
        self._once_hooks: set[LifecycleHook] = set()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def on(
        self,
        event: LifecycleEvent,
        handler: HookHandler | None = None,
        *,
        name: str = "",
        priority: int = 0,
        once: bool = False,
    ) -> Callable[[HookHandler], HookHandler] | None:
        """Register a lifecycle hook.

        Can be used as a decorator or called directly::

            registry.on("before_turn", my_handler)

            @registry.on("after_turn")
            async def handler(state, runtime):
                ...
        """
        if handler is not None:
            hook = LifecycleHook(event=event, handler=handler, name=name or handler.__name__, priority=priority, once=once)
            self._add_hook(event, hook)
            return None

        def decorator(fn: HookHandler) -> HookHandler:
            hook = LifecycleHook(event=event, handler=fn, name=name or fn.__name__, priority=priority, once=once)
            self._add_hook(event, hook)
            return fn

        return decorator

    def _add_hook(self, event: LifecycleEvent, hook: LifecycleHook) -> None:
        if event not in self._hooks:
            self._hooks[event] = []
        self._hooks[event].append(hook)
        self._hooks[event].sort(key=lambda h: h.priority, reverse=True)
        if hook.once:
            self._once_hooks.add(hook)

    def off(self, event: LifecycleEvent, handler: HookHandler) -> None:
        """Remove a hook handler from an event."""
        hooks = self._hooks.get(event, [])
        self._hooks[event] = [h for h in hooks if h.handler is not handler]
        # Also clean up once hooks
        self._once_hooks = {h for h in self._once_hooks if h.handler is not handler}

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def emit(self, event: LifecycleEvent, *args: Any, **kwargs: Any) -> list[Any]:
        """Emit an event, running all registered handlers.

        Handlers are called in priority order. If a handler is a coroutine
        function, it is awaited.
        """
        results: list[Any] = []
        hooks = list(self._hooks.get(event, []))

        for hook in hooks:
            try:
                result = hook.handler(*args, **kwargs)
                if hasattr(result, "__await__"):
                    result = await result
                results.append(result)
            except Exception as exc:
                logger.error(
                    "Hook %r handler %r failed: %s", event, hook.name, exc
                )

        # Clean up one-shot hooks
        for hook in hooks:
            if hook.once and hook in self._once_hooks:
                self._off_internal(event, hook)

        return results

    def emit_sync(self, event: LifecycleEvent, *args: Any, **kwargs: Any) -> list[Any]:
        """Synchronous version of emit for non-async contexts."""
        results: list[Any] = []
        hooks = list(self._hooks.get(event, []))

        for hook in hooks:
            try:
                result = hook.handler(*args, **kwargs)
                results.append(result)
            except Exception as exc:
                logger.error(
                    "Hook %r handler %r failed: %s", event, hook.name, exc
                )

        for hook in hooks:
            if hook.once and hook in self._once_hooks:
                self._off_internal(event, hook)

        return results

    def _off_internal(self, event: LifecycleEvent, hook: LifecycleHook) -> None:
        hooks = self._hooks.get(event, [])
        self._hooks[event] = [h for h in hooks if h is not hook]
        self._once_hooks.discard(hook)

    # ------------------------------------------------------------------
    # Query & management
    # ------------------------------------------------------------------

    def list_hooks(self, event: LifecycleEvent | None = None) -> dict[LifecycleEvent, list[LifecycleHook]]:
        """List registered hooks, optionally filtered by event."""
        if event is not None:
            return {event: list(self._hooks.get(event, []))}
        return {ev: list(hs) for ev, hs in self._hooks.items()}

    def clear(self) -> None:
        """Remove all registered hooks."""
        self._hooks.clear()
        self._once_hooks.clear()

    def handler_count(self, event: LifecycleEvent | None = None) -> int:
        """Count registered handlers."""
        if event is not None:
            return len(self._hooks.get(event, []))
        return sum(len(hs) for hs in self._hooks.values())