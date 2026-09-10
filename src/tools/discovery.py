"""Tool description, discovery, selection, statistics, and cost tracking.

Provides:
- ``ToolDescription`` — rich metadata beyond the basic ToolSpec
- ``ToolSelector`` — context-aware tool selection (filter/rank/top-k)
- ``ToolStatistics`` — usage tracking with cost estimates
- ``ToolDiscovery`` — unified discovery combining registry, MCP, and custom
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from src.tools.filesystem import ToolResult
from src.tools.registry import ToolRegistry, ToolSpec


# ── Tool descriptions ───────────────────────────────────────────────────


@dataclass
class ToolDescription:
    """Rich description for a tool, including examples and parameter info."""

    name: str
    """Tool name."""
    summary: str
    """One-line summary."""
    description: str
    """Full description."""
    examples: list[dict[str, Any]] = field(default_factory=list)
    """Usage examples: ``[{"args": {...}, "description": "..."}]``."""
    parameters: dict[str, Any] = field(default_factory=dict)
    """Parameter schema (JSON Schema compatible dict)."""
    return_value: str = ""
    """Description of the return value."""
    category: str = "custom"
    """Tool category."""
    tags: list[str] = field(default_factory=list)
    """Tags for discovery."""
    deprecated: bool = False
    """Whether the tool is deprecated."""
    source: str = "custom"
    """Origin: ``builtin``, ``custom``, ``mcp``."""

    def to_prompt(self) -> str:
        """Format as a prompt-friendly tool description block."""
        lines = [f"## {self.name}", "", self.description, ""]
        if self.parameters:
            lines.append("Parameters:")
            for param, schema in self.parameters.items():
                required = schema.get("required", False)
                req_mark = " (required)" if required else ""
                param_type = schema.get("type", "any")
                lines.append(f"  - `{param}` (`{param_type}`){req_mark}: {schema.get('description', '')}")
            lines.append("")
        if self.examples:
            lines.append("Examples:")
            for ex in self.examples[:2]:
                ex_desc = ex.get("description", "")
                ex_args = ex.get("args", {})
                lines.append(f"  - {ex_desc}")
                if ex_args:
                    lines.append(f"    `{ex_args}`")
            lines.append("")
        return "\n".join(lines)


# ── Tool statistics ─────────────────────────────────────────────────────


TOKEN_COST_PER_CALL: dict[str, float] = {
    "filesystem": 0.0001,
    "custom": 0.001,
    "mcp": 0.002,
}
"""Estimated USD cost per tool call by category."""

TOKEN_COST_DEFAULT = 0.0005


@dataclass
class ToolCallRecord:
    """A single recorded tool call."""

    tool_name: str
    category: str = "custom"
    timestamp: float = 0.0
    duration_ms: float = 0.0
    success: bool = True
    token_estimate: int = 0
    cost_estimate: float = 0.0


class ToolStatistics:
    """Tracks tool usage, latency, success rates, and cost estimates.

    Thread-safe.  Data is kept in-memory; for persistence see ``AuditLog``
    in the permissions module.
    """

    def __init__(self) -> None:
        self._records: list[ToolCallRecord] = []
        self._lock = Lock()
        self._max_records = 10_000

    def record_call(
        self,
        tool_name: str,
        category: str = "custom",
        duration_ms: float = 0.0,
        success: bool = True,
        token_estimate: int = 0,
    ) -> ToolCallRecord:
        """Record a tool call.

        Args:
            tool_name: Name of the tool called.
            category: Tool category (for cost estimation).
            duration_ms: Execution duration in milliseconds.
            success: Whether the call succeeded.
            token_estimate: Estimated token usage.

        Returns:
            The created record.
        """
        cost_per = TOKEN_COST_PER_CALL.get(category, TOKEN_COST_DEFAULT)
        record = ToolCallRecord(
            tool_name=tool_name,
            category=category,
            timestamp=time.time(),
            duration_ms=duration_ms,
            success=success,
            token_estimate=token_estimate,
            cost_estimate=token_estimate * cost_per,
        )
        with self._lock:
            self._records.append(record)
            if len(self._records) > self._max_records:
                self._records = self._records[-self._max_records:]
        return record

    def get_summary(self) -> dict[str, Any]:
        """Get summary statistics.

        Returns:
            Dict with total calls, success rate, avg latency, total cost, and
            per-tool breakdown.
        """
        with self._lock:
            total = len(self._records)
            if total == 0:
                return {"total_calls": 0}

            succeeded = sum(1 for r in self._records if r.success)
            total_cost = sum(r.cost_estimate for r in self._records)
            total_duration = sum(r.duration_ms for r in self._records)

            tool_breakdown: dict[str, dict[str, Any]] = {}
            for r in self._records:
                entry = tool_breakdown.setdefault(
                    r.tool_name,
                    {"calls": 0, "successes": 0, "total_duration_ms": 0.0, "total_cost": 0.0},
                )
                entry["calls"] += 1
                entry["successes"] += 1 if r.success else 0
                entry["total_duration_ms"] += r.duration_ms
                entry["total_cost"] += r.cost_estimate

            return {
                "total_calls": total,
                "success_rate": succeeded / total if total else 0,
                "avg_latency_ms": total_duration / total if total else 0,
                "total_cost_usd": round(total_cost, 6),
                "tool_breakdown": tool_breakdown,
            }

    def most_used(self, top_k: int = 5) -> list[tuple[str, int]]:
        """Get the most frequently called tools.

        Returns:
            List of ``(tool_name, call_count)`` sorted descending.
        """
        counts: dict[str, int] = {}
        with self._lock:
            for r in self._records:
                counts[r.tool_name] = counts.get(r.tool_name, 0) + 1
        sorted_counts = sorted(counts.items(), key=lambda x: -x[1])
        return sorted_counts[:top_k]

    def clear(self) -> None:
        """Clear all records."""
        with self._lock:
            self._records.clear()


# ── Tool selector ───────────────────────────────────────────────────────


class ToolSelector:
    """Context-aware tool selection.

    Filters and ranks tools based on relevance to a given context/prompt.
    Uses simple keyword-based scoring (no external AI service).
    """

    def rank_tools(
        self,
        tools: list[ToolSpec],
        context: str = "",
    ) -> list[tuple[ToolSpec, float]]:
        """Rank tools by relevance to a context string.

        Args:
            tools: List of tool specs to rank.
            context: Natural language context (e.g. the user's last message).

        Returns:
            List of ``(tool_spec, score)`` sorted by score descending.
        """
        if not context or not tools:
            return [(t, 0.0) for t in tools]

        context_lower = context.lower()
        context_words = set(context_lower.split())

        scored: list[tuple[ToolSpec, float]] = []
        for tool in tools:
            score = 0.0

            # Name matches (exact or partial)
            if tool.name.lower() in context_lower:
                score += 10.0
            for word in context_words:
                if word in tool.name.lower():
                    score += 5.0

            # Description matches
            desc_lower = tool.description.lower()
            for word in context_words:
                if word in desc_lower:
                    score += 2.0

            # Tag matches
            for tag in tool.tags:
                if tag.lower() in context_lower:
                    score += 3.0

            scored.append((tool, score))

        return sorted(scored, key=lambda x: -x[1])

    def select(
        self,
        tools: list[ToolSpec],
        context: str = "",
        top_k: int = 10,
        min_score: float = 1.0,
    ) -> list[ToolSpec]:
        """Select top-k tools relevant to the context.

        Args:
            tools: Available tools.
            context: Context string for ranking.
            top_k: Max tools to return.
            min_score: Minimum relevance score.

        Returns:
            Selected ``ToolSpec`` list.
        """
        ranked = self.rank_tools(tools, context)
        selected = [t for t, s in ranked if s >= min_score]
        return selected[:top_k]


# ── Unified discovery ───────────────────────────────────────────────────


class ToolDiscovery:
    """Unified discovery that aggregates tools from multiple sources.

    Provides a single ``find``/``search``/``list`` interface over the
    ``ToolRegistry``, MCP tools (if available), and custom providers.
    """

    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self._registry = registry or ToolRegistry()
        self._custom_providers: list[dict[str, Any]] = []
        self._selectors: list[ToolSelector] = [ToolSelector()]
        self._lock = Lock()

    @property
    def registry(self) -> ToolRegistry:
        """The underlying tool registry."""
        return self._registry

    def add_selector(self, selector: ToolSelector) -> None:
        """Add a custom selector."""
        self._selectors.append(selector)

    def list_tools(
        self,
        category: str | None = None,
        tags: list[str] | None = None,
    ) -> list[ToolSpec]:
        """List all available tools with optional filtering."""
        return self._registry.list_tools(category=category, tags=tags)

    def search(self, query: str) -> list[ToolSpec]:
        """Search tools by name or description."""
        return self._registry.search(query)

    def find(self, name: str) -> ToolSpec | None:
        """Find a single tool by name."""
        return self._registry.get(name)

    def select_for_context(
        self,
        context: str,
        top_k: int = 10,
        category: str | None = None,
    ) -> list[ToolSpec]:
        """Select tools relevant to a context string.

        Applies all registered selectors and merges results (union).

        Args:
            context: Context string.
            top_k: Max tools to return.
            category: Optional category filter.

        Returns:
            Selected ``ToolSpec`` list.
        """
        tools = self._registry.list_tools(category=category)
        if not tools:
            return []

        all_selected: set[str] = set()
        for selector in self._selectors:
            selected = selector.select(tools, context=context, top_k=top_k)
            for t in selected:
                all_selected.add(t.name)

        selected_tools = [t for t in tools if t.name in all_selected]
        return selected_tools[:top_k]

    def get_descriptions(
        self,
        names: list[str] | None = None,
        prompt_format: bool = True,
    ) -> list[ToolDescription] | str:
        """Get rich descriptions for tools.

        Args:
            names: Tool names to describe (None = all).
            prompt_format: If True, returns a single formatted prompt string.

        Returns:
            List of ``ToolDescription`` or a formatted prompt block string.
        """
        tools = (
            [self._registry.get(n) for n in names if self._registry.get(n)]
            if names
            else self._registry.list_tools()
        )

        descriptions = []
        for t in tools:
            desc = ToolDescription(
                name=t.name,
                summary=t.description.split(".")[0] if "." in t.description else t.description,
                description=t.description,
                category=t.category,
                tags=t.tags,
                source="builtin" if t.category == "filesystem" else "custom",
            )
            descriptions.append(desc)

        if prompt_format:
            return "\n".join(d.to_prompt() for d in descriptions)

        return descriptions


__all__ = [
    "ToolCallRecord",
    "ToolDescription",
    "ToolDiscovery",
    "ToolSelector",
    "ToolStatistics",
]