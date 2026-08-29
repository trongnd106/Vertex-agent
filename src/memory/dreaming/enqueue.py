"""End-of-turn dream trigger: an enqueue-only middleware hook.

Phase 6 trigger design (see `docs/phase-0-discovery.md` §12.9 + langchain
source): `AgentMiddleware` — the base class every deepagents middleware
subclasses — has **no** `on_tool_end`, but does expose `after_agent` /
`after_model` / `before_agent` / `before_model` (+ async variants) at
`langchain/agents/middleware/types.py` (`after_agent` at :266). These hooks
are registered as real LangGraph nodes (`langchain/agents/factory.py:1624-1645`),
so inside `after_agent` BOTH `get_config()["configurable"]["thread_id"]` and
`runtime.context.user_id` are resolvable (live-probed).

`after_agent` runs exactly once when the agent loop exits, making it the
correct end-of-turn site. The hook must NEVER dream synchronously — it only
calls the injected `enqueue(thread_id, user_id)` callback (queue `put`,
appender list, or scheduled job API). Processing happens elsewhere (cold-scan
`python -m src.memory.dreaming.scan`, or a queue-consuming worker in
production); Celery/BullMQ are explicitly out of scope for this task.
"""

from __future__ import annotations

from typing import Any, Callable

from langchain.agents.middleware import AgentMiddleware
from langgraph.config import get_config
from langgraph.runtime import Runtime

#: Enqueue signature: called as ``enqueue(thread_id, user_id)``.
EnqueueCallback = Callable[[str, str], None]


class EnqueueAfterTurnMiddleware(AgentMiddleware):
    """Enqueues ``(thread_id, user_id)`` at the end of every agent turn.

    Enqueue-only by design: the dream (or cold-scan worker) runs later, so the
    main agent's latency never includes dreaming. When the graph was invoked
    without a per-user context (``runtime.context`` is ``None``), the hook
    skips silently — there is no user namespace to dream into.
    """

    def __init__(self, enqueue: EnqueueCallback | None = None) -> None:
        self._enqueue = enqueue or (lambda _thread_id, _user_id: None)

    def after_agent(self, state: dict[str, Any], runtime: Runtime) -> None:
        del state  # hook observes; never mutates agent state
        config = get_config()
        thread_id = config.get("configurable", {}).get("thread_id")
        ctx = getattr(runtime, "context", None)
        user_id = getattr(ctx, "user_id", None) if ctx is not None else None
        if thread_id and user_id:
            self._enqueue(str(thread_id), str(user_id))
        return None


def make_enqueue_callback(target: Callable[[tuple[str, str]], None]) -> EnqueueCallback:
    """Adapt an arbitrary sink (``queue.Queue.put``, ``list.append``) to the
    ``enqueue(thread_id, user_id)`` callback signature."""
    return lambda thread_id, user_id: target((thread_id, user_id))


__all__ = ["EnqueueAfterTurnMiddleware", "EnqueueCallback", "make_enqueue_callback"]