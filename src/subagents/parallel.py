"""Parallel tool execution system.

Executes multiple tool calls concurrently using a thread pool,
with configurable worker limits, per-tool timeouts, error isolation,
and streaming support.

Inspired by chatbot-orchestrator's ``AgentExecutor``.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable

from src.tools.filesystem import ToolResult
from src.tools.registry import ToolRegistry


# ── Parallel execution types ────────────────────────────────────────────


@dataclass
class ParallelToolCall:
    """A single tool call within a parallel batch."""

    id: str
    tool_name: str
    args: dict[str, Any]
    kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParallelToolResult:
    """Result for a single tool call in a batch."""

    call_id: str
    tool_name: str
    result: ToolResult
    duration_ms: float = 0.0


@dataclass
class BatchResult:
    """Aggregated result from a parallel batch execution."""

    results: list[ParallelToolResult] = field(default_factory=list)
    total_duration_ms: float = 0.0
    success_count: int = 0
    failure_count: int = 0

    @property
    def all_successful(self) -> bool:
        return self.failure_count == 0

    @property
    def successful_results(self) -> list[ParallelToolResult]:
        return [r for r in self.results if r.result.success]

    @property
    def failed_results(self) -> list[ParallelToolResult]:
        return [r for r in self.results if not r.result.success]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": len(self.results),
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "total_duration_ms": self.total_duration_ms,
            "all_successful": self.all_successful,
            "results": [
                {
                    "call_id": r.call_id,
                    "tool_name": r.tool_name,
                    "success": r.result.success,
                    "data": str(r.result.data)[:500] if r.result.data else None,
                    "error": r.result.error,
                    "duration_ms": r.duration_ms,
                }
                for r in self.results
            ],
        }


# ── Parallel executor ───────────────────────────────────────────────────


class ParallelExecutor:
    """Executes multiple tool calls concurrently.

    Features:
    - ThreadPool-based execution
    - Configurable worker pool (max_workers)
    - Per-tool timeout
    - Error isolation (1 failure doesn't affect others)
    - Result streaming via callbacks
    """

    def __init__(
        self,
        registry: ToolRegistry,
        max_workers: int = 3,
    ) -> None:
        self._registry = registry
        self._max_workers = max_workers
        self._lock = threading.Lock()

    def execute_batch(
        self,
        calls: list[ParallelToolCall],
        *,
        timeout: float = 30.0,
        stream_callback: Callable[[ParallelToolResult], None] | None = None,
    ) -> BatchResult:
        """Execute a batch of tool calls in parallel.

        Args:
            calls: List of tool calls to execute.
            timeout: Per-tool timeout in seconds.
            stream_callback: Optional callback called as each tool completes.

        Returns:
            ``BatchResult`` with all results.
        """
        if not calls:
            return BatchResult()

        start = time.time()
        results: list[ParallelToolResult | None] = [None] * len(calls)
        batch_result = BatchResult()

        with ThreadPoolExecutor(max_workers=min(self._max_workers, len(calls))) as executor:
            future_map: dict[Future, int] = {}

            for i, call in enumerate(calls):
                future = executor.submit(self._execute_single, call, timeout)
                future_map[future] = i

            for future in as_completed(future_map):
                idx = future_map[future]
                try:
                    result = future.result()
                    results[idx] = result
                    if stream_callback:
                        stream_callback(result)
                except Exception as e:
                    err_result = ParallelToolResult(
                        call_id=calls[idx].id,
                        tool_name=calls[idx].tool_name,
                        result=ToolResult(success=False, error=f"Executor error: {e}"),
                    )
                    results[idx] = err_result

        batch_result.results = [r for r in results if r is not None]
        batch_result.success_count = sum(1 for r in batch_result.results if r.result.success)
        batch_result.failure_count = len(batch_result.results) - batch_result.success_count
        batch_result.total_duration_ms = (time.time() - start) * 1000

        return batch_result

    def _execute_single(self, call: ParallelToolCall, timeout: float) -> ParallelToolResult:
        """Execute a single tool call with timeout isolation."""
        t_start = time.time()
        try:
            result = self._registry.execute(call.tool_name, _timeout=timeout, **call.args)
        except Exception as e:
            result = ToolResult(success=False, error=f"Unexpected error: {e}")

        duration = (time.time() - t_start) * 1000
        return ParallelToolResult(
            call_id=call.id,
            tool_name=call.tool_name,
            result=result,
            duration_ms=duration,
        )


# ── Supported tool types ────────────────────────────────────────────────

SUPPORTED_TOOL_TYPES = {"tool", "plan", "mcpserver", "code_interpreter", "ragflow_tool"}
"""Tool types that the parallel executor supports by default."""


__all__ = [
    "BatchResult",
    "ParallelExecutor",
    "ParallelToolCall",
    "ParallelToolResult",
    "SUPPORTED_TOOL_TYPES",
]