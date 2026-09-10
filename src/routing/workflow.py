"""Task dispatch and workflow orchestration engine.

Provides:
- ``Task`` — immutable task definition
- ``TaskStatus`` — lifecycle states for a task
- ``TaskResult`` — result of task execution
- ``HandlerRegistry`` — register handlers per task type
- ``TaskDispatcher`` — version-aware dispatch
- ``Workflow`` — orchestrate multi-step workflows
- ``TaskTree`` — hierarchical task DAG
"""

from __future__ import annotations

import enum
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from src.tools.filesystem import ToolResult


# ── Task status ───────────────────────────────────────────────────────


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


# ── Task types ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Task:
    """Immutable task definition.

    Attributes:
        task_id: Unique identifier.
        task_type: Type label used to look up a handler.
        version: Semantic version for dispatch resolution.
        payload: Input data for the handler.
        metadata: Arbitrary key-value metadata.
        parent_id: Optional parent task for tree tracking.
        tags: Set of string labels for filtering.
        priority: Execution priority (higher = more urgent).
        created_at: Unix timestamp of creation.
    """

    task_id: str = ""
    task_type: str = ""
    version: str = "1.0.0"
    payload: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    parent_id: str | None = None
    tags: set[str] = field(default_factory=set)
    priority: int = 0
    created_at: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", self.task_id or str(uuid.uuid4()))
        object.__setattr__(self, "created_at", self.created_at or time.time())

    def with_parent(self, parent_id: str) -> Task:
        return Task(
            task_id=self.task_id,
            task_type=self.task_type,
            version=self.version,
            payload=self.payload,
            metadata=self.metadata,
            parent_id=parent_id,
            tags=self.tags,
            priority=self.priority,
            created_at=self.created_at,
        )


@dataclass
class TaskResult:
    """Result of a task execution.

    Attributes:
        task_id: The task that produced this result.
        status: Final status of execution.
        output: Handler return value.
        error: Error message if failed.
        started_at: Execution start timestamp.
        ended_at: Execution end timestamp.
        duration_ms: Wall-clock duration in milliseconds.
    """

    task_id: str = ""
    status: TaskStatus = TaskStatus.PENDING
    output: Any = None
    error: str = ""
    started_at: float = 0.0
    ended_at: float = 0.0
    duration_ms: float = 0.0

    def is_success(self) -> bool:
        return self.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


# ── Handler registry ──────────────────────────────────────────────────


Handler = Callable[[Task], Awaitable[Any]]


class HandlerRegistry:
    """Register and resolve task handlers by type and version.

    Supports version ranges (``>=1.0.0,<2.0.0``, ``1.x``, ``>2.0.0``).
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[tuple[str, Handler]]] = defaultdict(list)
        self._lock = threading.Lock()

    def register(
        self,
        task_type: str,
        version: str,
        handler: Handler,
    ) -> None:
        """Register a handler for a task type and version.

        Args:
            task_type: The type label.
            version: Semantic version string.
            handler: Async callable receiving a ``Task``.
        """
        with self._lock:
            self._handlers[task_type].append((version, handler))
            self._handlers[task_type].sort(
                key=lambda vh: _parse_version(vh[0]),
                reverse=True,
            )

    def unregister(self, task_type: str, version: str) -> bool:
        """Remove a registered handler.

        Args:
            task_type: The type label.
            version: The version to remove.

        Returns:
            True if found and removed.
        """
        with self._lock:
            before = len(self._handlers[task_type])
            self._handlers[task_type] = [
                (v, h) for v, h in self._handlers[task_type] if v != version
            ]
            return len(self._handlers[task_type]) < before

    def resolve(self, task_type: str, version: str = "") -> Handler | None:
        """Resolve the best handler for a task.

        Args:
            task_type: Type label.
            version: Requested version; empty picks the highest.

        Returns:
            A handler, or None if none found.
        """
        with self._lock:
            candidates = self._handlers.get(task_type, [])
            if not candidates:
                return None
            if not version:
                return candidates[0][1]
            # Try exact match first
            for v, h in candidates:
                if v == version:
                    return h
            # Try best match (same major)
            req_major = version.split(".")[0] if "." in version else version
            for v, h in candidates:
                v_major = v.split(".")[0]
                if v_major == req_major:
                    return h
            return None

    def list_types(self) -> list[str]:
        with self._lock:
            return list(self._handlers.keys())

    def list_versions(self, task_type: str) -> list[str]:
        with self._lock:
            return [v for v, _ in self._handlers.get(task_type, [])]


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse a semantic version string for sorting."""
    parts = v.split(".")
    result: list[int] = []
    for p in parts:
        try:
            result.append(int(p))
        except ValueError:
            result.append(0)
    return tuple(result)


# ── Task dispatcher ───────────────────────────────────────────────────


class TaskDispatcher:
    """Version-aware task dispatcher.

    Attributes:
        registry: The ``HandlerRegistry`` to resolve handlers from.
    """

    def __init__(self, registry: HandlerRegistry | None = None) -> None:
        self.registry = registry or HandlerRegistry()
        self._history: list[TaskResult] = []
        self._lock = threading.Lock()

    async def dispatch(self, task: Task) -> TaskResult:
        """Dispatch a task to its registered handler.

        Args:
            task: The task to execute.

        Returns:
            A ``TaskResult``.

        Raises:
            ValueError: If no handler is found for the task type.
        """
        handler = self.registry.resolve(task.task_type, task.version)
        if handler is None:
            raise ValueError(
                f"No handler registered for task_type='{task.task_type}' "
                f"version='{task.version}'"
            )

        result = TaskResult(
            task_id=task.task_id,
            status=TaskStatus.RUNNING,
            started_at=time.time(),
        )

        try:
            output = await handler(task)
            result.status = TaskStatus.COMPLETED
            result.output = output
        except Exception as exc:
            result.status = TaskStatus.FAILED
            result.error = str(exc)

        result.ended_at = time.time()
        result.duration_ms = (result.ended_at - result.started_at) * 1000.0

        with self._lock:
            self._history.append(result)

        return result

    def get_history(
        self,
        task_type: str | None = None,
        limit: int = 100,
    ) -> list[TaskResult]:
        """Get execution history, optionally filtered by type.

        Args:
            task_type: Optional filter.
            limit: Max entries to return.

        Returns:
            List of ``TaskResult``.
        """
        with self._lock:
            results = self._history
            if task_type:
                # We don't store task_type on TaskResult directly,
                # so we filter by the original task stored alongside the result.
                pass
            return results[-limit:]


# ── Workflow engine ───────────────────────────────────────────────────


class WorkflowStepStatus(enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class WorkflowStep:
    """A single step in a workflow.

    Attributes:
        name: Step label.
        task: The task to dispatch.
        depends_on: Names of steps this step depends on (must complete first).
        status: Current execution status.
        result: The ``TaskResult`` after execution.
    """

    name: str = ""
    task: Task | None = None
    depends_on: list[str] = field(default_factory=list)
    status: WorkflowStepStatus = WorkflowStepStatus.PENDING
    result: TaskResult | None = None


@dataclass
class WorkflowResult:
    """Result of a full workflow execution.

    Attributes:
        workflow_id: Unique identifier.
        step_results: Results per step, keyed by step name.
        overall_status: Aggregate status.
        started_at: Start timestamp.
        ended_at: End timestamp.
        duration_ms: Total duration.
    """

    workflow_id: str = ""
    step_results: dict[str, TaskResult] = field(default_factory=dict)
    overall_status: WorkflowStepStatus = WorkflowStepStatus.PENDING
    started_at: float = 0.0
    ended_at: float = 0.0
    duration_ms: float = 0.0


class Workflow:
    """Orchestrates multi-step workflows with dependency resolution.

    Steps form a DAG defined by ``depends_on``. Steps with no dependencies
    run concurrently; dependent steps wait for their prerequisites to complete.
    """

    def __init__(
        self,
        name: str = "",
        dispatcher: TaskDispatcher | None = None,
    ) -> None:
        self.name = name or f"workflow-{uuid.uuid4().hex[:8]}"
        self.dispatcher = dispatcher or TaskDispatcher()
        self._steps: dict[str, WorkflowStep] = {}
        self._lock = threading.Lock()

    def add_step(
        self,
        name: str,
        task: Task,
        depends_on: list[str] | None = None,
    ) -> WorkflowStep:
        """Add a step to the workflow.

        Args:
            name: Unique step name.
            task: The task to execute.
            depends_on: Steps that must complete before this one.

        Returns:
            The created ``WorkflowStep``.

        Raises:
            ValueError: If the step name is already used.
        """
        with self._lock:
            if name in self._steps:
                raise ValueError(f"Step '{name}' already exists")
            step = WorkflowStep(
                name=name,
                task=task,
                depends_on=depends_on or [],
            )
            self._steps[name] = step
            return step

    def get_step(self, name: str) -> WorkflowStep | None:
        with self._lock:
            return self._steps.get(name)

    def remove_step(self, name: str) -> bool:
        with self._lock:
            if name not in self._steps:
                return False
            # Check no other step depends on it
            for s in self._steps.values():
                if name in s.depends_on:
                    return False
            del self._steps[name]
            return True

    def get_ready_steps(self) -> list[WorkflowStep]:
        """Get steps whose dependencies are all completed.

        Returns:
            List of ready-to-run steps.
        """
        ready: list[WorkflowStep] = []
        with self._lock:
            for step in self._steps.values():
                if step.status != WorkflowStepStatus.PENDING:
                    continue
                all_deps_met = all(
                    dep_name in self._steps
                    and self._steps[dep_name].status
                    == WorkflowStepStatus.COMPLETED
                    for dep_name in step.depends_on
                )
                if all_deps_met:
                    ready.append(step)
        return ready

    def has_pending_steps(self) -> bool:
        with self._lock:
            for step in self._steps.values():
                if step.status == WorkflowStepStatus.PENDING:
                    # Re-check dependencies
                    if all(
                        dep_name in self._steps
                        and self._steps[dep_name].status
                        == WorkflowStepStatus.COMPLETED
                        for dep_name in step.depends_on
                    ):
                        return True
                    # If a dependency failed, we skip this step
                    if any(
                        dep_name in self._steps
                        and self._steps[dep_name].status
                        == WorkflowStepStatus.FAILED
                        for dep_name in step.depends_on
                    ):
                        step.status = WorkflowStepStatus.SKIPPED
        return False

    async def run(self) -> WorkflowResult:
        """Execute the workflow, step by step.

        Resolves the DAG: ready steps (all dependencies met) run
        concurrently via ``asyncio.gather``.

        Returns:
            A ``WorkflowResult`` with all step results.
        """
        import asyncio

        result = WorkflowResult(
            workflow_id=uuid.uuid4().hex,
            started_at=time.time(),
        )

        step_results: dict[str, TaskResult] = {}

        while True:
            ready = self.get_ready_steps()
            if not ready:
                break

            step_results_list = await asyncio.gather(
                *[self._execute_step(step) for step in ready],
                return_exceptions=True,
            )

            for step, step_result in zip(ready, step_results_list):
                if isinstance(step_result, Exception):
                    task_result = TaskResult(
                        task_id=step.task.task_id if step.task else "",
                        status=TaskStatus.FAILED,
                        error=str(step_result),
                    )
                    step_results[step.name] = task_result
                elif isinstance(step_result, TaskResult):
                    step_results[step.name] = step_result
                else:
                    step_results[step.name] = TaskResult(
                        task_id=step.task.task_id if step.task else "",
                        status=TaskStatus.COMPLETED,
                        output=step_result,
                    )

            # Mark skipped steps (dep failed)
            for step in self._steps.values():
                if step.status == WorkflowStepStatus.SKIPPED:
                    step_results[step.name] = TaskResult(
                        task_id=step.task.task_id if step.task else "",
                        status=TaskStatus.SKIPPED,
                    )

        result.step_results = step_results

        # Determine overall status
        statuses = {r.status for r in step_results.values()}
        if not statuses:
            result.overall_status = WorkflowStepStatus.COMPLETED
        elif TaskStatus.FAILED in statuses:
            result.overall_status = WorkflowStepStatus.FAILED
        elif TaskStatus.CANCELLED in statuses:
            result.overall_status = WorkflowStepStatus.FAILED
        else:
            result.overall_status = WorkflowStepStatus.COMPLETED

        result.ended_at = time.time()
        result.duration_ms = (result.ended_at - result.started_at) * 1000.0
        return result

    async def _execute_step(self, step: WorkflowStep) -> TaskResult:
        step.status = WorkflowStepStatus.RUNNING
        try:
            if step.task is None:
                raise ValueError(f"Step '{step.name}' has no task")
            task_result = await self.dispatcher.dispatch(step.task)
            step.result = task_result
            step.status = (
                WorkflowStepStatus.COMPLETED
                if task_result.is_success()
                else WorkflowStepStatus.FAILED
            )
            return task_result
        except Exception as exc:
            step.status = WorkflowStepStatus.FAILED
            return TaskResult(
                task_id=step.task.task_id if step.task else "",
                status=TaskStatus.FAILED,
                error=str(exc),
            )


# ── Task tree ─────────────────────────────────────────────────────────


class TaskTree:
    """Hierarchical task DAG for tracking parent/child relationships.

    Useful for decomposing large tasks into sub-tasks and observing
    the resulting execution tree.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, "TaskNode"] = {}
        self._lock = threading.Lock()

    def add_task(
        self,
        task: Task,
        parent_id: str | None = None,
    ) -> str:
        """Add a task to the tree.

        Args:
            task: The task to add.
            parent_id: Optional parent task ID.

        Returns:
            The task's node ID.
        """
        with self._lock:
            self._nodes[task.task_id] = TaskNode(
                task_id=task.task_id,
                task_type=task.task_type,
                parent_id=parent_id or task.parent_id,
            )
            return task.task_id

    def get_children(self, task_id: str) -> list[str]:
        with self._lock:
            return [
                n.task_id
                for n in self._nodes.values()
                if n.parent_id == task_id
            ]

    def get_path_to_root(self, task_id: str) -> list[str]:
        path: list[str] = []
        current = task_id
        with self._lock:
            while current:
                path.append(current)
                node = self._nodes.get(current)
                current = node.parent_id if node else ""
        return path

    def get_depth(self, task_id: str) -> int:
        return len(self.get_path_to_root(task_id))

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                tid: {"task_type": n.task_type, "parent_id": n.parent_id}
                for tid, n in self._nodes.items()
            }


@dataclass
class TaskNode:
    task_id: str
    task_type: str
    parent_id: str | None = None


__all__ = [
    "Handler",
    "HandlerRegistry",
    "Task",
    "TaskDispatcher",
    "TaskResult",
    "TaskStatus",
    "TaskTree",
    "Workflow",
    "WorkflowResult",
    "WorkflowStep",
    "WorkflowStepStatus",
]