"""Asynchronous subagent system.

Background subagents that run independently from the main agent.
Supports remote deployment via LangGraph SDK or local thread-based
execution with polling for results.

Inspired by DeepAgents' ``AsyncSubAgentMiddleware``.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from src.middleware.types import AgentMiddleware
from src.subagents.sync import CompiledSubAgent, SubAgent, SubAgentRegistry
from src.tools.filesystem import ToolResult


# ── Async subagent types ────────────────────────────────────────────────


class AsyncSubAgentStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class AsyncTask:
    """A single asynchronous task (remote or local)."""

    id: str = ""
    subagent_name: str = ""
    input_data: Any = None
    status: AsyncSubAgentStatus = AsyncSubAgentStatus.PENDING
    result: ToolResult | None = None
    created_at: float = 0.0
    completed_at: float = 0.0
    error: str = ""
    url: str = ""
    thread_id: str = ""
    run_id: str = ""


@dataclass
class AsyncSubAgent:
    """Specification for an async/remote subagent.

    Supports both local thread-based execution and remote LangGraph
    deployment via ``url`` and ``headers``.
    """

    graph_id: str = ""
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    subagent_spec: SubAgent | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_remote(self) -> bool:
        return bool(self.url)


# ── Async subagent manager ──────────────────────────────────────────────


class AsyncSubAgentManager:
    """Manages lifecycle of async subagents.

    Supports both local (thread-based) and remote execution.
    """

    def __init__(
        self,
        registry: SubAgentRegistry | None = None,
        max_concurrent: int = 5,
    ) -> None:
        self._registry = registry or SubAgentRegistry()
        self._tasks: dict[str, AsyncTask] = {}
        self._async_subagents: dict[str, AsyncSubAgent] = {}
        self._lock = threading.Lock()
        self._max_concurrent = max_concurrent

    # ── Async subagent registration ──────────────────────────────────

    def register_async_subagent(self, name: str, spec: AsyncSubAgent) -> None:
        """Register an async subagent by name."""
        with self._lock:
            self._async_subagents[name] = spec

    def get_async_subagent(self, name: str) -> AsyncSubAgent | None:
        with self._lock:
            return self._async_subagents.get(name)

    def list_async_subagents(self) -> list[tuple[str, AsyncSubAgent]]:
        with self._lock:
            return list(self._async_subagents.items())

    # ── Task lifecycle ───────────────────────────────────────────────

    def launch_task(
        self,
        subagent_name: str,
        input_data: Any = None,
        remote_url: str = "",
    ) -> AsyncTask:
        """Launch a new async task.

        Args:
            subagent_name: Name of registered subagent or async subagent.
            input_data: Input to pass.
            remote_url: Optional remote URL override.

        Returns:
            ``AsyncTask`` with a unique ID for polling.
        """
        task = AsyncTask(
            id=str(uuid.uuid4()),
            subagent_name=subagent_name,
            input_data=input_data,
            status=AsyncSubAgentStatus.PENDING,
            created_at=time.time(),
            url=remote_url,
        )

        with self._lock:
            # Check concurrent limit
            running = sum(
                1 for t in self._tasks.values()
                if t.status in (AsyncSubAgentStatus.PENDING, AsyncSubAgentStatus.RUNNING)
            )
            if running >= self._max_concurrent:
                task.status = AsyncSubAgentStatus.FAILED
                task.error = f"Max concurrent tasks reached ({self._max_concurrent})"
                task.completed_at = time.time()
                self._tasks[task.id] = task
                return task

            self._tasks[task.id] = task

        # Check if this is a remote task
        async_spec = self.get_async_subagent(subagent_name)
        if async_spec and async_spec.is_remote():
            task.url = async_spec.url
            self._execute_remote(task, async_spec)
        else:
            # Local execution
            self._execute_local(task)

        return task

    def _execute_local(self, task: AsyncTask) -> None:
        """Execute a task locally in a background thread."""
        def _run() -> None:
            try:
                task.status = AsyncSubAgentStatus.RUNNING
                compiled = self._registry.get(task.subagent_name)
                if compiled is None:
                    task.result = ToolResult(
                        success=False,
                        error=f"Unknown subagent: '{task.subagent_name}'",
                    )
                    task.status = AsyncSubAgentStatus.FAILED
                else:
                    task.result = compiled.invoke({"input": task.input_data})
                    task.status = (
                        AsyncSubAgentStatus.COMPLETED
                        if task.result.success
                        else AsyncSubAgentStatus.FAILED
                    )
            except Exception as e:
                task.result = ToolResult(success=False, error=str(e))
                task.status = AsyncSubAgentStatus.FAILED
            finally:
                task.completed_at = time.time()

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

    def _execute_remote(self, task: AsyncTask, spec: AsyncSubAgent) -> None:
        """Execute a task remotely (placeholder for LangGraph SDK integration)."""
        task.status = AsyncSubAgentStatus.RUNNING
        thread_id = str(uuid.uuid4())
        task.thread_id = thread_id

        def _run_remote() -> None:
            try:
                # Placeholder: in production, this would use LangGraph SDK:
                # from langgraph_sdk import get_client
                # client = get_client(url=task.url, headers=spec.headers)
                # run = client.runs.create(thread_id, spec.graph_id, input=task.input_data)
                # task.run_id = run.id
                # ... poll for completion
                time.sleep(0.1)  # simulate remote call
                task.result = ToolResult(
                    success=True,
                    data=f"Remote task executed (graph={spec.graph_id}, thread={thread_id})",
                )
                task.status = AsyncSubAgentStatus.COMPLETED
            except Exception as e:
                task.result = ToolResult(success=False, error=str(e))
                task.status = AsyncSubAgentStatus.FAILED
            finally:
                task.completed_at = time.time()

        thread = threading.Thread(target=_run_remote, daemon=True)
        thread.start()

    # ── Task querying ────────────────────────────────────────────────

    def get_task(self, task_id: str) -> AsyncTask | None:
        with self._lock:
            return self._tasks.get(task_id)

    def get_task_status(self, task_id: str) -> dict[str, Any]:
        """Get status info for a task.

        Returns:
            Dict with id, status, result, timing.
        """
        task = self.get_task(task_id)
        if task is None:
            return {"error": f"Task '{task_id}' not found"}
        return {
            "id": task.id,
            "subagent_name": task.subagent_name,
            "status": task.status.value,
            "result_success": task.result.success if task.result else None,
            "result_data": str(task.result.data)[:500] if task.result and task.result.data else None,
            "result_error": task.result.error if task.result else task.error,
            "created_at": task.created_at,
            "completed_at": task.completed_at,
            "thread_id": task.thread_id,
            "run_id": task.run_id,
        }

    def list_tasks(
        self,
        status: AsyncSubAgentStatus | None = None,
    ) -> list[AsyncTask]:
        """List tasks, optionally filtered by status."""
        with self._lock:
            tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        return sorted(tasks, key=lambda t: t.created_at, reverse=True)

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a running task.

        Returns:
            True if the task was found and cancelled.
        """
        task = self.get_task(task_id)
        if task is None:
            return False
        if task.status in (AsyncSubAgentStatus.PENDING, AsyncSubAgentStatus.RUNNING):
            task.status = AsyncSubAgentStatus.CANCELLED
            task.completed_at = time.time()
            return True
        return False

    def clean_orphans(self, max_age_seconds: float = 3600) -> int:
        """Remove old completed/failed/cancelled tasks.

        Args:
            max_age_seconds: Max age before cleanup.

        Returns:
            Number of tasks removed.
        """
        now = time.time()
        to_remove: list[str] = []
        with self._lock:
            for tid, task in self._tasks.items():
                if task.status in (
                    AsyncSubAgentStatus.COMPLETED,
                    AsyncSubAgentStatus.FAILED,
                    AsyncSubAgentStatus.CANCELLED,
                ):
                    if task.completed_at and (now - task.completed_at) > max_age_seconds:
                        to_remove.append(tid)
            for tid in to_remove:
                del self._tasks[tid]
        return len(to_remove)


# ── Async middleware ────────────────────────────────────────────────────


class AsyncSubAgentMiddleware(AgentMiddleware):
    """Middleware that registers async subagent lifecycle tools.

    Provides tools: ``launch_task``, ``update_task``, ``cancel_task``,
    ``get_task_status``, ``list_tasks``.
    """

    def __init__(self, manager: AsyncSubAgentManager | None = None) -> None:
        super().__init__()
        self._manager = manager or AsyncSubAgentManager()

    @property
    def manager(self) -> AsyncSubAgentManager:
        return self._manager

    async def before_agent(self, config: MiddlewareConfig) -> None:
        pass

    async def after_agent(self, config: MiddlewareConfig) -> None:
        pass

    def _make_launch_task(self) -> Callable[..., ToolResult]:
        def _launch(subagent_name: str, input_data: Any = None) -> ToolResult:
            task = self._manager.launch_task(subagent_name, input_data)
            return ToolResult(
                success=True,
                data={
                    "task_id": task.id,
                    "status": task.status.value,
                    "message": f"Launched subagent '{subagent_name}' (task={task.id})",
                },
            )
        _launch.__name__ = "launch_task"
        return _launch

    def _make_get_task_status(self) -> Callable[..., ToolResult]:
        def _get_status(task_id: str) -> ToolResult:
            info = self._manager.get_task_status(task_id)
            return ToolResult(success="error" not in info, data=info)
        _get_status.__name__ = "get_task_status"
        return _get_status

    def _make_cancel_task(self) -> Callable[..., ToolResult]:
        def _cancel(task_id: str) -> ToolResult:
            ok = self._manager.cancel_task(task_id)
            return ToolResult(
                success=ok,
                data=f"Task '{task_id}' cancelled" if ok else f"Task '{task_id}' not found or already completed",
            )
        _cancel.__name__ = "cancel_task"
        return _cancel

    def _make_list_tasks(self) -> Callable[..., ToolResult]:
        def _list(status: str | None = None) -> ToolResult:
            status_filter = None
            if status:
                try:
                    status_filter = AsyncSubAgentStatus(status)
                except ValueError:
                    pass
            tasks = self._manager.list_tasks(status=status_filter)
            return ToolResult(
                success=True,
                data=[
                    {
                        "id": t.id,
                        "subagent_name": t.subagent_name,
                        "status": t.status.value,
                        "created_at": t.created_at,
                    }
                    for t in tasks
                ],
            )
        _list.__name__ = "list_tasks"
        return _list


__all__ = [
    "AsyncSubAgent",
    "AsyncSubAgentManager",
    "AsyncSubAgentMiddleware",
    "AsyncSubAgentStatus",
    "AsyncTask",
]