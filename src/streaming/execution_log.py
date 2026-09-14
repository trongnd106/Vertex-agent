"""Execution log — step-by-step agent task execution tracking.

Provides an ``ExecutionLogger`` that records each step of an agent's
execution so failures can be traced to the exact node/step where they
occurred.  Works alongside the ``Tracer``, ``StructuredLogger``, and
``MetricsCollector`` — it adds execution-level granularity that those
higher-level observability tools do not capture.

Design:
- Each run (invocation) gets a unique *run ID*.
- Each step within a run records: step number, node name, status,
  duration, error (if any), and a snapshot of relevant state keys.
- A step is one of: ``pending → running → completed | failed``.
- The log is kept in-memory as a list of ``ExecutionStep`` and can be
  dumped as human-readable text or JSON at any time.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


# ── Status ───────────────────────────────────────────────────────────────


class StepStatus(Enum):
    """Status of an individual execution step."""

    PENDING = auto()
    """Step is registered but not yet started."""
    RUNNING = auto()
    """Step is currently executing."""
    COMPLETED = auto()
    """Step completed successfully."""
    FAILED = auto()
    """Step failed with an error."""
    SKIPPED = auto()
    """Step was skipped (conditional routing)."""


# ── Data types ───────────────────────────────────────────────────────────


@dataclass
class ExecutionStep:
    """A single step in the agent execution trace.

    Attributes:
        step_number: 1-based step index within the run.
        node_name: Name of the graph node / agent step.
        node_type: Type hint (e.g. ``"agent"``, ``"tool"``, ``"router"``,
            ``"subagent"``).
        status: Current execution status.
        started_at: Monotonic timestamp when execution began.
        completed_at: Monotonic timestamp when execution finished.
        duration_ms: Wall-clock duration in milliseconds.
        error: Error message if the step failed, or ``None``.
        error_type: Fully-qualified exception class name (e.g.
            ``"ValueError"``).
        input_preview: Truncated view of the step's input state keys.
        output_preview: Truncated view of the step's output.
        metadata: Arbitrary extra key-value pairs.
    """

    step_number: int = 0
    node_name: str = ""
    node_type: str = "general"
    status: StepStatus = StepStatus.PENDING
    started_at: float = 0.0
    completed_at: float = 0.0
    duration_ms: float = 0.0
    error: str | None = None
    error_type: str | None = None
    input_preview: dict[str, str] = field(default_factory=dict)
    output_preview: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def elapsed_ms(self) -> float:
        """Return the current elapsed time if still running, or total duration."""
        if self.completed_at > 0:
            return self.duration_ms
        if self.started_at > 0:
            return round((time.monotonic() - self.started_at) * 1000, 2)
        return 0.0

    @property
    def is_terminal(self) -> bool:
        """Whether this step has reached a terminal state."""
        return self.status in (
            StepStatus.COMPLETED,
            StepStatus.FAILED,
            StepStatus.SKIPPED,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_number": self.step_number,
            "node_name": self.node_name,
            "node_type": self.node_type,
            "status": self.status.name.lower(),
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "error_type": self.error_type,
            "input_preview": self.input_preview,
            "output_preview": self.output_preview,
            "metadata": self.metadata,
        }

    def format_summary(self) -> str:
        """One-line human-readable summary of this step."""
        status_tag = {
            StepStatus.PENDING: "⏳",
            StepStatus.RUNNING: "▶",
            StepStatus.COMPLETED: "✅",
            StepStatus.FAILED: "❌",
            StepStatus.SKIPPED: "⏭",
        }.get(self.status, "?")

        parts = [
            f"{status_tag} Step #{self.step_number}",
            f"[{self.node_name}]",
            f"({self.node_type})",
        ]
        if self.duration_ms > 0:
            parts.append(f"— {self.duration_ms:.0f}ms")
        if self.error:
            parts.append(f"ERROR: {self.error}")
        return " ".join(parts)

    def format_detail(self) -> str:
        """Multi-line detailed description of this step."""
        lines = [
            f"{'='*60}",
            f"  Step #{self.step_number}: {self.node_name}",
            f"  Type:   {self.node_type}",
            f"  Status: {self.status.name.lower()}",
        ]
        if self.duration_ms > 0:
            lines.append(f"  Duration: {self.duration_ms:.0f}ms")
        if self.error:
            lines.append(f"  Error:   {self.error}")
            if self.error_type:
                lines.append(f"  Type:    {self.error_type}")
        if self.input_preview:
            lines.append(f"  Input keys: {', '.join(self.input_preview.keys())}")
        if self.output_preview:
            lines.append(f"  Output:  {self.output_preview[:200]}")
        if self.metadata:
            lines.append(f"  Meta:    {self.metadata}")
        lines.append(f"{'='*60}")
        return "\n".join(lines)


@dataclass
class ExecutionRun:
    """A complete execution run composed of multiple steps.

    Attributes:
        run_id: Unique identifier for this run.
        started_at: Timestamp when the run started.
        completed_at: Timestamp when the run completed.
        total_steps: Total number of steps executed.
        failed_steps: Number of steps that failed.
        status: Overall run status.
        error: Top-level error if the run failed.
        steps: Ordered list of execution steps.
    """

    run_id: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0
    total_duration_ms: float = 0.0
    total_steps: int = 0
    failed_steps: int = 0
    status: str = "pending"
    error: str | None = None
    error_type: str | None = None
    steps: list[ExecutionStep] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "total_duration_ms": self.total_duration_ms,
            "total_steps": self.total_steps,
            "failed_steps": self.failed_steps,
            "status": self.status,
            "error": self.error,
            "error_type": self.error_type,
            "steps": [s.to_dict() for s in self.steps],
            "metadata": self.metadata,
        }

    def format_summary(self) -> str:
        """Human-readable run summary showing the step chain."""
        status_icon = "✅" if self.status == "completed" else "❌"
        lines = [
            f"{'─'*60}",
            f"  Execution Run: {self.run_id}  {status_icon}",
            f"  Status: {self.status}",
            f"  Steps:  {self.total_steps} total, {self.failed_steps} failed",
        ]
        if self.total_duration_ms > 0:
            lines.append(f"  Total:  {self.total_duration_ms:.0f}ms")
        if self.error:
            lines.append(f"  Error:  {self.error}")
        lines.append("")
        for step in self.steps:
            lines.append(f"  {step.format_summary()}")
        lines.append(f"{'─'*60}")
        return "\n".join(lines)


# ── ExecutionLogger ────────────────────────────────────────────────────────


class ExecutionLogger:
    """Thread-safe, step-by-step execution logger for agent tasks.

    Typical usage::

        logger = ExecutionLogger()
        logger.start_run("run-1", metadata={"input": "..."})

        step = logger.start_step("agent_node", node_type="agent")
        try:
            result = execute_node(...)
            logger.complete_step(step, output_preview=str(result)[:200])
        except Exception as exc:
            logger.fail_step(step, error=exc)

        run = logger.finish_run()
        print(run.format_summary())            # human-readable
        print(json.dumps(run.to_dict()))       # machine-readable

    The logger is designed to be used from middleware, graph nodes, and
    subagent code — wherever an execution step happens.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current_run: ExecutionRun | None = None
        self._step_counter: int = 0
        self._active_steps: dict[str, ExecutionStep] = {}  # node_name → step

    # ── Properties ──────────────────────────────────────────────────────

    @property
    def current_run(self) -> ExecutionRun | None:
        """The currently active run, or ``None``."""
        with self._lock:
            return self._current_run

    @property
    def active_steps(self) -> dict[str, ExecutionStep]:
        """Active (running/pending) steps keyed by node name."""
        with self._lock:
            return dict(self._active_steps)

    @property
    def last_step(self) -> ExecutionStep | None:
        """The most recently recorded step, or ``None``."""
        with self._lock:
            if self._current_run and self._current_run.steps:
                return self._current_run.steps[-1]
            return None

    @property
    def failed_step(self) -> ExecutionStep | None:
        """The first failed step, or ``None`` if none have failed."""
        with self._lock:
            if self._current_run:
                for step in self._current_run.steps:
                    if step.status == StepStatus.FAILED:
                        return step
            return None

    # ── Run lifecycle ───────────────────────────────────────────────────

    def start_run(
        self,
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Start a new execution run.

        Args:
            run_id: Optional explicit run ID.  Auto-generated if omitted.
            metadata: Optional metadata attached to the run.

        Returns:
            The run ID.
        """
        with self._lock:
            run_id = run_id or f"run_{uuid.uuid4().hex[:12]}"
            self._current_run = ExecutionRun(
                run_id=run_id,
                started_at=time.monotonic(),
                status="running",
                metadata=metadata or {},
            )
            self._step_counter = 0
            self._active_steps.clear()
            return run_id

    def finish_run(self, error: Exception | None = None) -> ExecutionRun:
        """Mark the current run as completed or failed.

        Fails any still-active steps before finishing.

        Args:
            error: Optional top-level exception that caused the run to end.

        Returns:
            The completed ``ExecutionRun``.
        """
        with self._lock:
            if self._current_run is None:
                raise RuntimeError("No active run to finish")

            # Fail any lingering active steps
            for step in self._active_steps.values():
                if not step.is_terminal:
                    step.status = StepStatus.FAILED
                    step.completed_at = time.monotonic()
                    step.duration_ms = round(
                        (step.completed_at - step.started_at) * 1000, 2
                    )
                    step.error = "Run finished while step was still active"

            self._current_run.completed_at = time.monotonic()
            self._current_run.total_duration_ms = round(
                (self._current_run.completed_at - self._current_run.started_at) * 1000, 2
            )
            self._current_run.total_steps = self._step_counter
            self._current_run.failed_steps = sum(
                1 for s in self._current_run.steps if s.status == StepStatus.FAILED
            )

            if error:
                self._current_run.status = "failed"
                self._current_run.error = str(error)
                self._current_run.error_type = type(error).__qualname__
            elif self._current_run.failed_steps > 0:
                self._current_run.status = "failed"
            else:
                self._current_run.status = "completed"

            self._active_steps.clear()
            return self._current_run

    def reset(self) -> None:
        """Clear the current run and all steps."""
        with self._lock:
            self._current_run = None
            self._step_counter = 0
            self._active_steps.clear()

    # ── Step lifecycle ──────────────────────────────────────────────────

    def start_step(
        self,
        node_name: str,
        node_type: str = "general",
        input_state: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ExecutionStep:
        """Record the start of a new execution step.

        Args:
            node_name: Name of the node/step being executed.
            node_type: Type hint (``"agent"``, ``"tool"``, ``"subagent"``, etc.).
            input_state: Optional state dict — only key names are recorded
                (full values can bloat the log).
            metadata: Optional extra key-value pairs.

        Returns:
            The newly created ``ExecutionStep`` (already appended to the run).
        """
        with self._lock:
            self._step_counter += 1

            # Build a lightweight preview of input keys
            input_preview: dict[str, str] = {}
            if input_state:
                for k, v in input_state.items():
                    if isinstance(v, str):
                        input_preview[k] = v[:60] + "..." if len(v) > 60 else v
                    elif isinstance(v, (list, dict)):
                        input_preview[k] = f"<{type(v).__name__} len={len(v)}>"
                    else:
                        input_preview[k] = str(v)[:60]

            step = ExecutionStep(
                step_number=self._step_counter,
                node_name=node_name,
                node_type=node_type,
                status=StepStatus.RUNNING,
                started_at=time.monotonic(),
                input_preview=input_preview,
                metadata=metadata or {},
            )
            self._active_steps[node_name] = step
            if self._current_run is not None:
                self._current_run.steps.append(step)
            return step

    def complete_step(
        self,
        step: ExecutionStep | str,
        output_preview: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ExecutionStep:
        """Mark a step as completed successfully.

        Args:
            step: The ``ExecutionStep`` object, or a node name string
                matching an active step.
            output_preview: Optional truncated preview of the output.
            metadata: Optional extra key-value pairs to merge in.

        Returns:
            The updated ``ExecutionStep``.
        """
        with self._lock:
            resolved = self._resolve_step(step)
            if resolved is None:
                raise ValueError(f"No active step found for: {step}")

            resolved.status = StepStatus.COMPLETED
            resolved.completed_at = time.monotonic()
            resolved.duration_ms = round(
                (resolved.completed_at - resolved.started_at) * 1000, 2
            )
            resolved.output_preview = output_preview[:500]
            if metadata:
                resolved.metadata.update(metadata)

            self._active_steps.pop(resolved.node_name, None)
            return resolved

    def fail_step(
        self,
        step: ExecutionStep | str,
        error: Exception | str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ExecutionStep:
        """Mark a step as failed.

        Args:
            step: The ``ExecutionStep`` object, or a node name string
                matching an active step.
            error: The exception or error message that caused the failure.
            metadata: Optional extra key-value pairs to merge in.

        Returns:
            The updated ``ExecutionStep``.
        """
        with self._lock:
            resolved = self._resolve_step(step)
            if resolved is None:
                raise ValueError(f"No active step found for: {step}")

            resolved.status = StepStatus.FAILED
            resolved.completed_at = time.monotonic()
            resolved.duration_ms = round(
                (resolved.completed_at - resolved.started_at) * 1000, 2
            )

            if isinstance(error, Exception):
                resolved.error = str(error)
                resolved.error_type = type(error).__qualname__
            elif isinstance(error, str):
                resolved.error = error
                resolved.error_type = "Unknown"
            else:
                resolved.error = None
                resolved.error_type = None

            if metadata:
                resolved.metadata.update(metadata)

            self._active_steps.pop(resolved.node_name, None)
            return resolved

    def skip_step(
        self,
        node_name: str,
        reason: str = "",
    ) -> ExecutionStep | None:
        """Record a step that was skipped (e.g. conditional routing).

        Args:
            node_name: Name of the skipped node.
            reason: Optional reason for skipping.

        Returns:
            The created ``ExecutionStep``, or ``None`` if no run is active.
        """
        with self._lock:
            if self._current_run is None:
                return None
            self._step_counter += 1
            step = ExecutionStep(
                step_number=self._step_counter,
                node_name=node_name,
                node_type="skipped",
                status=StepStatus.SKIPPED,
                completed_at=time.monotonic(),
                error=reason or None,
            )
            self._current_run.steps.append(step)
            return step

    # ── Helpers ─────────────────────────────────────────────────────────

    def _resolve_step(self, step: ExecutionStep | str) -> ExecutionStep | None:
        """Resolve a step reference to an ``ExecutionStep``."""
        if isinstance(step, ExecutionStep):
            return step
        return self._active_steps.get(step)

    def get_run_summary(self) -> str:
        """Get a human-readable summary of the current run."""
        with self._lock:
            if self._current_run is None:
                return "(no active run)"
            return self._current_run.format_summary()

    def get_failed_step_info(self) -> str | None:
        """Return a one-line description of which step failed, if any.

        Returns ``None`` when there is no failure, making it safe to
        call unconditionally at the end of a run.
        """
        with self._lock:
            if self._current_run is None:
                return None
            for step in self._current_run.steps:
                if step.status == StepStatus.FAILED:
                    return (
                        f"❌ Step #{step.step_number} [{step.node_name}] "
                        f"failed after {step.duration_ms:.0f}ms: {step.error}"
                    )
            return None

    def to_json(self, indent: int = 2) -> str:
        """Serialize the current run to JSON."""
        import json
        with self._lock:
            if self._current_run is None:
                return json.dumps({"run": None})
            return json.dumps(self._current_run.to_dict(), indent=indent)


__all__ = [
    "ExecutionLogger",
    "ExecutionRun",
    "ExecutionStep",
    "StepStatus",
]