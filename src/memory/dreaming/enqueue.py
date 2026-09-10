"""End-of-turn dream trigger: an enqueue-only middleware hook.

``after_agent`` runs exactly once when the agent loop exits, making it the
correct end-of-turn site. The hook must NEVER dream synchronously — it only
calls the injected ``enqueue(thread_id, user_id)`` callback.
"""

from __future__ import annotations

from typing import Any, Callable

from langchain.agents.middleware.types import AgentMiddleware, Runtime

#: Enqueue signature: called as ``enqueue(thread_id, user_id)``.
EnqueueCallback = Callable[[str, str], None]


class EnqueueAfterTurnMiddleware(AgentMiddleware):
    """Enqueues ``(thread_id, user_id)`` at the end of every agent turn.

    Enqueue-only by design: the dream (or cold-scan worker) runs later, so the
    main agent's latency never includes dreaming.

    Thread ID comes from ``runtime.execution_info.thread_id`` and user_id from
    ``runtime.context.user_id`` (set via ``context=UserContext(user_id=...)``).
    """

    tools: list[Any] = []

    def __init__(self, enqueue: EnqueueCallback | None = None) -> None:
        super().__init__()
        self._enqueue = enqueue or (lambda _thread_id, _user_id: None)

    def after_agent(self, state: dict[str, Any], runtime: Runtime[Any]) -> dict[str, Any] | None:
        """Synchronous after-agent hook (for invoke/stream paths).

        Enqueues ``(thread_id, user_id)`` from the runtime context.
        """
        thread_id = ""
        user_id = ""
        exec_info = getattr(runtime, "execution_info", None)
        if exec_info is not None:
            thread_id = getattr(exec_info, "thread_id", "") or ""
        ctx = getattr(runtime, "context", None)
        if ctx is not None:
            user_id = str(ctx.user_id) if hasattr(ctx, "user_id") and ctx.user_id else ""
        if thread_id and user_id:
            self._enqueue(str(thread_id), str(user_id))
        return None

    async def aafter_agent(self, state: dict[str, Any], runtime: Runtime[Any]) -> dict[str, Any] | None:
        """Async after-agent hook (for ainvoke/astream paths)."""
        thread_id = ""
        user_id = ""
        exec_info = getattr(runtime, "execution_info", None)
        if exec_info is not None:
            thread_id = getattr(exec_info, "thread_id", "") or ""
        ctx = getattr(runtime, "context", None)
        if ctx is not None:
            user_id = str(ctx.user_id) if hasattr(ctx, "user_id") and ctx.user_id else ""
        if thread_id and user_id:
            self._enqueue(str(thread_id), str(user_id))
        return None


def make_enqueue_callback(target: Callable[[tuple[str, str]], None]) -> EnqueueCallback:
    """Adapt an arbitrary sink to the ``enqueue(thread_id, user_id)`` callback."""
    return lambda thread_id, user_id: target((thread_id, user_id))


__all__ = ["EnqueueAfterTurnMiddleware", "EnqueueCallback", "make_enqueue_callback"]