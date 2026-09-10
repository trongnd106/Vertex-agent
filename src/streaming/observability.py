"""Observability & tracing system — metrics, logging, tracing, health checks.

Provides:
- ``MetricsCollector`` — token usage, tool execution time, streaming latency
- ``StructuredLogger`` — structured logging for agent operations
- ``Tracer`` — span-based tracing for tool execution, middleware, subagents
- ``HealthCheck`` — agent health endpoint helpers
- ``DebugMode`` — step-by-step execution trace with state snapshots
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


# ── Metrics ───────────────────────────────────────────────────────────


@dataclass
class MetricSnapshot:
    """A snapshot of metrics at a point in time."""

    token_usage: dict[str, int] = field(default_factory=lambda: {"prompt": 0, "completion": 0, "total": 0})
    tool_execution_time: dict[str, float] = field(default_factory=dict)
    streaming_latency: dict[str, float] = field(default_factory=lambda: {"avg_ms": 0.0, "max_ms": 0.0, "count": 0})
    error_rate: dict[str, float] = field(default_factory=lambda: {"total": 0, "errors": 0, "rate": 0.0})
    agent_iterations: int = 0
    session_count: int = 0


class MetricsCollector:
    """Collects and reports agent metrics.

    Thread-safe. Accumulates counters and timing data for monitoring.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._token_usage: dict[str, int] = {"prompt": 0, "completion": 0, "total": 0}
        self._tool_times: dict[str, list[float]] = defaultdict(list)
        self._stream_latencies: list[float] = []
        self._error_count = 0
        self._total_operations = 0
        self._iterations = 0
        self._sessions = 0

    def record_tokens(self, prompt: int = 0, completion: int = 0) -> None:
        with self._lock:
            self._token_usage["prompt"] += prompt
            self._token_usage["completion"] += completion
            self._token_usage["total"] += prompt + completion

    def record_tool_execution(self, tool_name: str, duration_ms: float) -> None:
        with self._lock:
            self._tool_times[tool_name].append(duration_ms)
            self._total_operations += 1

    def record_chunk_latency(self, latency_ms: float) -> None:
        with self._lock:
            self._stream_latencies.append(latency_ms)

    def record_error(self) -> None:
        with self._lock:
            self._error_count += 1
            self._total_operations += 1

    def record_iteration(self) -> None:
        with self._lock:
            self._iterations += 1

    def record_session(self) -> None:
        with self._lock:
            self._sessions += 1

    def snapshot(self) -> MetricSnapshot:
        """Take a snapshot of current metrics."""
        with self._lock:
            tool_avg: dict[str, float] = {}
            for name, times in self._tool_times.items():
                tool_avg[name] = sum(times) / len(times) if times else 0.0

            avg_latency = sum(self._stream_latencies) / len(self._stream_latencies) if self._stream_latencies else 0.0
            max_latency = max(self._stream_latencies) if self._stream_latencies else 0.0
            error_rate = (self._error_count / self._total_operations * 100) if self._total_operations > 0 else 0.0

            return MetricSnapshot(
                token_usage=dict(self._token_usage),
                tool_execution_time=tool_avg,
                streaming_latency={
                    "avg_ms": round(avg_latency, 2),
                    "max_ms": round(max_latency, 2),
                    "count": len(self._stream_latencies),
                },
                error_rate={
                    "total": self._total_operations,
                    "errors": self._error_count,
                    "rate": round(error_rate, 2),
                },
                agent_iterations=self._iterations,
                session_count=self._sessions,
            )

    def reset(self) -> None:
        with self._lock:
            self._token_usage = {"prompt": 0, "completion": 0, "total": 0}
            self._tool_times.clear()
            self._stream_latencies.clear()
            self._error_count = 0
            self._total_operations = 0
            self._iterations = 0
            self._sessions = 0


# ── Structured logging ────────────────────────────────────────────────


class StructuredLogger:
    """Provides structured logging for agent operations.

    Outputs JSON-formatted log lines with consistent fields.
    """

    def __init__(self, name: str = "vertex-agent", level: int = logging.INFO) -> None:
        self._logger = logging.getLogger(name)
        self._logger.setLevel(level)

    def _log(self, level: int, event: str, **fields: Any) -> None:
        record = {
            "event": event,
            "timestamp": time.time(),
            **fields,
        }
        self._logger.log(level, json.dumps(record, ensure_ascii=False))

    def info(self, event: str, **fields: Any) -> None:
        self._log(logging.INFO, event, **fields)

    def warning(self, event: str, **fields: Any) -> None:
        self._log(logging.WARNING, event, **fields)

    def error(self, event: str, **fields: Any) -> None:
        self._log(logging.ERROR, event, **fields)

    def debug(self, event: str, **fields: Any) -> None:
        self._log(logging.DEBUG, event, **fields)


# ── Tracing ───────────────────────────────────────────────────────────


@dataclass
class Span:
    """A single trace span representing one operation."""

    name: str
    span_id: str = ""
    parent_id: str | None = None
    trace_id: str = ""
    category: str = "general"
    tags: dict[str, str] = field(default_factory=dict)
    start_time: float = 0.0
    end_time: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.span_id:
            self.span_id = str(uuid.uuid4())[:8]
        if not self.trace_id:
            self.trace_id = str(uuid.uuid4())[:8]
        if not self.start_time:
            self.start_time = time.time()

    def close(self) -> None:
        """Close the span, recording end time."""
        self.end_time = time.time()

    @property
    def duration_ms(self) -> float:
        if self.end_time and self.start_time:
            return round((self.end_time - self.start_time) * 1000, 2)
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "span_id": self.span_id,
            "parent_id": self.parent_id,
            "trace_id": self.trace_id,
            "category": self.category,
            "tags": self.tags,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


class Tracer:
    """Span-based tracer for agent operations.

    Creates and manages spans for tool execution, middleware,
    subagents, and streaming operations.
    """

    def __init__(self) -> None:
        self._spans: list[Span] = []
        self._stack: list[Span] = []
        self._lock = threading.Lock()
        self._active_trace_id: str = ""

    @property
    def active_trace_id(self) -> str:
        return self._active_trace_id

    def start_trace(self, name: str = "agent_run") -> str:
        """Start a new trace and return its trace ID."""
        trace_id = str(uuid.uuid4())[:8]
        self._active_trace_id = trace_id
        span = Span(name=name, trace_id=trace_id, category="trace")
        with self._lock:
            self._spans.append(span)
            self._stack.append(span)
        return trace_id

    def start_span(
        self,
        name: str,
        category: str = "general",
        tags: dict[str, str] | None = None,
    ) -> Span:
        """Start a new span within the current trace."""
        trace_id = self._active_trace_id or str(uuid.uuid4())[:8]
        parent = self._stack[-1] if self._stack else None
        span = Span(
            name=name,
            trace_id=trace_id,
            parent_id=parent.span_id if parent else None,
            category=category,
            tags=tags or {},
        )
        with self._lock:
            self._spans.append(span)
            self._stack.append(span)
        return span

    def end_span(self, span: Span | None = None) -> None:
        """End a span.

        Args:
            span: Span to end. If None, ends the current top span.
        """
        with self._lock:
            if span is None:
                if self._stack:
                    span = self._stack.pop()
            else:
                if self._stack and self._stack[-1].span_id == span.span_id:
                    self._stack.pop()
            if span:
                span.close()

    def end_trace(self) -> None:
        """End all spans and the current trace."""
        with self._lock:
            for span in reversed(self._stack):
                span.close()
            self._stack.clear()
            self._active_trace_id = ""

    def get_spans(self, trace_id: str | None = None) -> list[Span]:
        """Get spans, optionally filtered by trace ID."""
        with self._lock:
            if trace_id:
                return [s for s in self._spans if s.trace_id == trace_id]
            return list(self._spans)

    def clear(self) -> None:
        with self._lock:
            self._spans.clear()
            self._stack.clear()
            self._active_trace_id = ""


# ── Health check ──────────────────────────────────────────────────────


@dataclass
class HealthStatus:
    """Agent health status."""

    status: str = "ok"  # "ok" | "degraded" | "error"
    version: str = "0.3.0"
    uptime_seconds: float = 0.0
    active_sessions: int = 0
    errors_last_minute: int = 0
    components: dict[str, str] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)


class HealthCheck:
    """Agent health check helper.

    Tracks component status and provides health snapshots.
    """

    def __init__(self) -> None:
        self._start_time = time.time()
        self._components: dict[str, str] = {}
        self._errors: list[float] = []
        self._active_sessions = 0
        self._lock = threading.Lock()

    def register_component(self, name: str, status: str = "ok") -> None:
        with self._lock:
            self._components[name] = status

    def set_component_status(self, name: str, status: str) -> None:
        with self._lock:
            self._components[name] = status

    def record_error(self) -> None:
        with self._lock:
            self._errors.append(time.time())

    def set_active_sessions(self, count: int) -> None:
        with self._lock:
            self._active_sessions = count

    def get_status(self) -> HealthStatus:
        with self._lock:
            now = time.time()
            recent_errors = sum(1 for t in self._errors if (now - t) < 60)
            overall = "ok"
            if any(s == "error" for s in self._components.values()):
                overall = "error"
            elif any(s == "degraded" for s in self._components.values()):
                overall = "degraded"

            return HealthStatus(
                status=overall,
                uptime_seconds=round(now - self._start_time, 2),
                active_sessions=self._active_sessions,
                errors_last_minute=recent_errors,
                components=dict(self._components),
            )


# ── Debug mode ────────────────────────────────────────────────────────


@dataclass
class DebugSnapshot:
    """A snapshot of agent state at a point in the execution."""

    step: int
    node: str
    timestamp: float
    state: dict[str, Any] = field(default_factory=dict)
    spans: list[dict[str, Any]] = field(default_factory=list)


class DebugMode:
    """Step-by-step execution trace with state snapshots.

    Captures state before and after each node execution for debugging.
    """

    def __init__(self) -> None:
        self._enabled = False
        self._snapshots: list[DebugSnapshot] = []
        self._step = 0

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def snapshots(self) -> list[DebugSnapshot]:
        return list(self._snapshots)

    def capture(self, node: str, state: dict[str, Any], spans: list[Span] | None = None) -> DebugSnapshot | None:
        """Capture a debug snapshot.

        Args:
            node: Name of the node being executed.
            state: Current agent state.
            spans: Active spans at this point.

        Returns:
            The snapshot if debug is enabled, else None.
        """
        if not self._enabled:
            return None
        self._step += 1
        snapshot = DebugSnapshot(
            step=self._step,
            node=node,
            timestamp=time.time(),
            state=_truncate_state(state),
            spans=[s.to_dict() for s in (spans or [])],
        )
        self._snapshots.append(snapshot)
        return snapshot

    def clear(self) -> None:
        self._snapshots.clear()
        self._step = 0

    def summary(self) -> str:
        """Return a human-readable summary of all snapshots."""
        lines = [f"Debug Mode: {len(self._snapshots)} snapshots"]
        for snap in self._snapshots:
            lines.append(f"  Step {snap.step}: {snap.node}")
            keys = list(snap.state.keys())
            if keys:
                lines.append(f"    State keys: {', '.join(keys[:10])}")
        return "\n".join(lines)


def _truncate_state(state: dict[str, Any], max_str_len: int = 200) -> dict[str, Any]:
    """Truncate large string values in state for snapshot readability."""
    truncated: dict[str, Any] = {}
    for k, v in state.items():
        if isinstance(v, str) and len(v) > max_str_len:
            truncated[k] = v[:max_str_len] + "..."
        elif isinstance(v, list) and len(v) > 50:
            truncated[k] = f"<list of {len(v)} items>"
        elif isinstance(v, dict) and len(v) > 50:
            truncated[k] = f"<dict of {len(v)} keys>"
        else:
            truncated[k] = v
    return truncated


__all__ = [
    "DebugMode",
    "DebugSnapshot",
    "HealthCheck",
    "HealthStatus",
    "MetricsCollector",
    "MetricSnapshot",
    "Span",
    "StructuredLogger",
    "Tracer",
]