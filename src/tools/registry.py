"""Tool registry and business tool infrastructure.

Provides the ``ToolRegistry`` for registering, discovering, and executing tools,
plus base classes and helpers for building custom business tools.
"""

from __future__ import annotations

import copy
import inspect
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from src.tools.filesystem import FILESYSTEM_TOOLS, ToolResult


# ── Tool definitions ─────────────────────────────────────────────────────


@dataclass
class ToolSpec:
    """Specification for a registered tool."""

    name: str
    """Unique tool name."""
    description: str
    """Human-readable description."""
    fn: Callable[..., ToolResult]
    """The callable implementing the tool."""
    category: str = "custom"
    """Tool category (filesystem, custom, mcp, etc.)."""
    timeout: float = 60.0
    """Max execution time in seconds."""
    retry_enabled: bool = True
    """Whether to retry on failure."""
    max_retries: int = 2
    """Maximum number of retry attempts."""
    permissions: list[str] = field(default_factory=lambda: ["*"])
    """Permission operations required."""
    tags: list[str] = field(default_factory=list)
    """Arbitrary tags for discovery/filtering."""
    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional metadata."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-serializable dict (without the function)."""
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "timeout": self.timeout,
            "retry_enabled": self.retry_enabled,
            "max_retries": self.max_retries,
            "permissions": self.permissions,
            "tags": self.tags,
            "metadata": self.metadata,
        }


# ── Tool chaining ────────────────────────────────────────────────────────


def chain_tools(*tools: Callable[..., ToolResult]) -> Callable[..., ToolResult]:
    """Chain multiple tools so the output of each feeds the next.

    Each tool receives the previous result's ``data`` as its first positional
    argument.  The chain stops early if any tool returns an error.

    Args:
        *tools: Tool functions to chain in order.

    Returns:
        A combined callable.
    """

    def _chain(*args: Any, **kwargs: Any) -> ToolResult:
        data: Any = args[0] if args else kwargs
        for i, tool in enumerate(tools):
            if i == 0:
                result = tool(data, **kwargs) if isinstance(data, dict) else tool(data)
            else:
                if isinstance(result, ToolResult) and not result.success:
                    return ToolResult(
                        success=False,
                        error=f"Chain stopped at tool {i}: {result.error}",
                    )
                result = tool(result.data)
        return result or ToolResult(success=True, data=data)

    return _chain


# ── Tool registry ────────────────────────────────────────────────────────


class ToolRegistry:
    """Thread-safe registry for discovering and executing tools.

    Maintains a flat namespace of ``ToolSpec`` entries aggregated from
    multiple sources: built-in filesystem tools, registered custom tools,
    and MCP-provided tools.
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self._lock = threading.Lock()

        # Register built-in filesystem tools
        self._register_filesystem_tools()

    # ── Registration ──────────────────────────────────────────────────

    def _register_filesystem_tools(self) -> None:
        for name, spec in FILESYSTEM_TOOLS.items():
            self._tools[name] = ToolSpec(
                name=spec["name"],
                description=spec["description"],
                fn=spec["fn"],
                category=spec.get("category", "filesystem"),
                permissions=spec.get("permission_operations", ["read"]),
                tags=["builtin", "filesystem"],
                timeout=30.0,
            )

    def register(
        self,
        name: str,
        description: str,
        fn: Callable[..., ToolResult],
        category: str = "custom",
        timeout: float = 60.0,
        retry_enabled: bool = True,
        max_retries: int = 2,
        permissions: list[str] | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ToolSpec:
        """Register a new tool.

        Args:
            name: Unique tool name. Overwrites existing if name collides.
            description: Human-readable description.
            fn: The callable.
            category: Category label.
            timeout: Max execution time in seconds.
            retry_enabled: Whether to auto-retry.
            max_retries: Max retry attempts.
            permissions: Required permission operations.
            tags: Discovery tags.
            metadata: Extra metadata.

        Returns:
            The created ``ToolSpec``.
        """
        spec = ToolSpec(
            name=name,
            description=description,
            fn=fn,
            category=category,
            timeout=timeout,
            retry_enabled=retry_enabled,
            max_retries=max_retries,
            permissions=permissions or ["*"],
            tags=tags or [],
            metadata=metadata or {},
        )
        with self._lock:
            self._tools[name] = spec
        return spec

    def unregister(self, name: str) -> bool:
        """Remove a tool by name.

        Returns:
            True if the tool existed and was removed.
        """
        with self._lock:
            if name in self._tools:
                del self._tools[name]
                return True
            return False

    # ── Discovery ─────────────────────────────────────────────────────

    def get(self, name: str) -> ToolSpec | None:
        """Get a tool spec by name."""
        return self._tools.get(name)

    def list_tools(
        self,
        category: str | None = None,
        tags: list[str] | None = None,
    ) -> list[ToolSpec]:
        """List registered tools, optionally filtered.

        Args:
            category: Filter by category.
            tags: Filter by tags (tool must have all listed tags).

        Returns:
            Matching ``ToolSpec`` list.
        """
        with self._lock:
            result = list(self._tools.values())

        if category:
            result = [t for t in result if t.category == category]
        if tags:
            result = [t for t in result if all(tag in t.tags for tag in tags)]

        return sorted(result, key=lambda t: t.name)

    def search(self, query: str) -> list[ToolSpec]:
        """Search tools by name or description.

        Args:
            query: Case-insensitive search string.

        Returns:
            Matching ``ToolSpec`` list.
        """
        q = query.lower()
        with self._lock:
            return sorted(
                [
                    t
                    for t in self._tools.values()
                    if q in t.name.lower() or q in t.description.lower()
                ],
                key=lambda t: t.name,
            )

    # ── Execution ─────────────────────────────────────────────────────

    def execute(
        self,
        name: str,
        *args: Any,
        _timeout: float | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        """Execute a tool by name.

        Args:
            name: Tool name.
            *args: Positional arguments passed to the tool function.
            _timeout: Optional per-call timeout override.
            **kwargs: Keyword arguments.

        Returns:
            Tool execution result.
        """
        spec = self.get(name)
        if spec is None:
            return ToolResult(success=False, error=f"Unknown tool: {name}")

        timeout = _timeout or spec.timeout
        fn = spec.fn
        last_error: str = ""

        for attempt in range((spec.max_retries if spec.retry_enabled else 0) + 1):
            try:
                result = fn(*args, **kwargs)
                if not isinstance(result, ToolResult):
                    return ToolResult(success=True, data=result)
                return result
            except TimeoutError as e:
                last_error = f"Timeout after {timeout}s: {e}"
                break
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                if attempt < spec.max_retries and spec.retry_enabled:
                    time.sleep(1.0)
                    continue
                break

        return ToolResult(success=False, error=last_error)

    # ── Bulk operations ───────────────────────────────────────────────

    def to_deep_agent_tools(self) -> list[ToolSpec]:
        """Return all tools in a format suitable for deep agent config."""
        with self._lock:
            return list(self._tools.values())

    def copy(self) -> ToolRegistry:
        """Create an independent copy of this registry."""
        new = ToolRegistry.__new__(ToolRegistry)
        new._lock = threading.Lock()
        with self._lock:
            new._tools = copy.deepcopy(self._tools)
        return new


# Global default registry
_default_registry: ToolRegistry | None = None
_registry_lock = threading.Lock()


def get_default_registry() -> ToolRegistry:
    """Get or create the global default ``ToolRegistry``."""
    global _default_registry
    if _default_registry is None:
        with _registry_lock:
            if _default_registry is None:
                _default_registry = ToolRegistry()
    return _default_registry


def reset_default_registry() -> None:
    """Reset the global registry (useful for testing)."""
    global _default_registry
    with _registry_lock:
        _default_registry = None


__all__ = [
    "ToolRegistry",
    "ToolSpec",
    "chain_tools",
    "get_default_registry",
    "reset_default_registry",
]