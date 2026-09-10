"""Tool calling middleware — interception, patching, permissions, and exclusion.

Provides a family of middleware that manage tool calls throughout the
agent lifecycle:

- ``PatchToolCallsMiddleware`` — fix JSON errors, add missing fields
- ``ToolingMiddleware`` — manage tool registry, enable/disable tools
- ``PermissionsMiddleware`` — FilesystemPermission rules (allow/deny/interrupt)
- ``ToolExclusionMiddleware`` — remove excluded tools from the available set
- ``ToolCallLimitMiddleware`` — limit tool calls per turn
- ``ToolSelectionMiddleware`` — filter tools based on context

Inspired by DeepAgents' ``patch_tool_calls.py``, ``permissions.py``,
``_tool_exclusion.py``, and chatbot-orchestrator's tooling pipeline.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from src.middleware.types import (
    AgentMiddleware,
    MiddlewareConfig,
    MiddlewareResult,
    ModelRequest,
)

# ── Permission types ─────────────────────────────────────────────────────


class PermissionAction(Enum):
    """Action to take when a permission check matches."""

    ALLOW = auto()
    """Allow the operation."""
    DENY = auto()
    """Deny the operation."""
    INTERRUPT = auto()
    """Interrupt for human approval."""


@dataclass
class FilesystemPermission:
    """Permission rule for filesystem operations.

    Similar to DeepAgents' ``FilesystemPermission`` used in
    ``backends/filesystem.py``.
    """

    path: str
    """Path pattern (glob or prefix)."""
    action: PermissionAction = PermissionAction.ALLOW
    """What action to take when this pattern matches."""
    description: str = ""
    """Human-readable description of this permission."""


# ── PatchToolCallsMiddleware ─────────────────────────────────────────────


@dataclass
class ToolCall:
    """Represents a single tool call parsed from model output."""

    id: str = ""
    """Tool call ID."""
    name: str = ""
    """Tool name."""
    args: dict[str, Any] = field(default_factory=dict)
    """Tool arguments."""
    raw: str = ""
    """Raw JSON string (for error recovery)."""


class PatchToolCallsMiddleware(AgentMiddleware[Any]):
    """Middleware that patches and fixes tool calls from the model.

    Common fixes:
    - Parse malformed JSON arguments
    - Add missing required fields with defaults
    - Fix trailing commas in JSON
    - Batch fix: process multiple tool calls in one pass
    """

    name = "patch_tool_calls"

    def __init__(self) -> None:
        super().__init__()
        self._fixed_count: int = 0

    @property
    def fixed_count(self) -> int:
        """Number of tool calls fixed."""
        return self._fixed_count

    def after_agent(
        self,
        state: dict[str, Any],
        runtime: Any,
        config: MiddlewareConfig,
    ) -> MiddlewareResult | None:
        """Patch tool calls in the last assistant message."""
        messages = state.get("messages", [])
        if not messages:
            return None

        last = messages[-1]
        if not isinstance(last, dict):
            return None
        if last.get("role") != "assistant":
            return None

        tool_calls = last.get("tool_calls")
        if not tool_calls:
            return None

        patched = False
        for tc in tool_calls:
            if self._patch_tool_call(tc):
                patched = True

        if patched:
            messages[-1] = last

        return None

    def _patch_tool_call(self, tc: dict[str, Any]) -> bool:
        """Attempt to fix a single tool call.

        Args:
            tc: Tool call dict to patch (mutated in place).

        Returns:
            True if any fix was applied.
        """
        patched = False

        # Fix 1: Parse string args that aren't valid JSON
        args = tc.get("args")
        if isinstance(args, str):
            try:
                tc["args"] = self._parse_json_strict(args)
                patched = True
            except json.JSONDecodeError:
                fixed = self._fix_malformed_json(args)
                if fixed is not None:
                    tc["args"] = fixed
                    patched = True

        # Fix 2: Ensure args is a dict
        if not isinstance(tc.get("args"), dict):
            tc["args"] = {}
            patched = True

        # Fix 3: Add missing id field
        if not tc.get("id"):
            tc["id"] = f"call_{hash(str(tc)) & 0xFFFFFFFF:08x}"
            patched = True

        # Fix 4: Add missing name field
        if not tc.get("name"):
            tc["name"] = "unknown_tool"
            patched = True

        if patched:
            self._fixed_count += 1

        return patched

    def _parse_json_strict(self, text: str) -> dict[str, Any] | list[Any]:
        """Parse JSON with strict settings.

        Args:
            text: JSON string to parse.

        Returns:
            Parsed dict or list.

        Raises:
            json.JSONDecodeError: If parsing fails.
        """
        return json.loads(text)

    def _fix_malformed_json(self, text: str) -> dict[str, Any] | None:
        """Attempt to fix and parse malformed JSON.

        Fixes:
        - Replace single quotes with double quotes
        - Remove trailing commas
        - Wrap bare keys in quotes

        Args:
            text: Potentially malformed JSON string.

        Returns:
            Parsed dict, or None if unfixable.
        """
        # Fix 1: Replace single quotes with double quotes
        fixed = text.replace("'", '"')

        # Fix 2: Remove trailing commas before } and ]
        fixed = re.sub(r",\s*}", "}", fixed)
        fixed = re.sub(r",\s*]", "]", fixed)

        # Fix 3: Add quotes around bare keys
        fixed = re.sub(r"(?<![{,])\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:", r'"\1":', fixed)

        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            return None


# ── ToolingMiddleware ────────────────────────────────────────────────────


class ToolingMiddleware(AgentMiddleware[Any]):
    """Manages the tool registry and decides which tools are enabled.

    Routes tool calls to their implementations and handles tool results.
    """

    name = "tooling"

    def __init__(
        self,
        tools: list[Any] | None = None,
    ) -> None:
        super().__init__()
        self._tools = list(tools) if tools else []
        self._tool_registry: dict[str, Any] = {}

    @property
    def tools(self) -> list[Any]:
        return list(self._tools)

    @tools.setter
    def tools(self, value: list[Any]) -> None:
        self._tools = list(value)

    def before_agent(
        self,
        state: dict[str, Any],
        runtime: Any,
        config: MiddlewareConfig,
    ) -> MiddlewareResult | None:
        """Build tool registry and inject available tools into state."""
        # Build tool registry by name
        for tool in self._tools:
            tool_name = getattr(tool, "name", None) or getattr(tool, "__name__", str(tool))
            self._tool_registry[tool_name] = tool

        # Add tool info to state
        available = list(self._tool_registry.keys())
        state["_available_tools"] = available

        return None

    def after_agent(
        self,
        state: dict[str, Any],
        runtime: Any,
        config: MiddlewareConfig,
    ) -> MiddlewareResult | None:
        """Execute tool calls and inject results into state."""
        messages = state.get("messages", [])
        if not messages:
            return None

        last = messages[-1]
        if not isinstance(last, dict) or last.get("role") != "assistant":
            return None

        tool_calls = last.get("tool_calls", [])
        if not tool_calls:
            return None

        results = []
        for tc in tool_calls:
            tool_name = tc.get("name", "")
            tool_fn = self._tool_registry.get(tool_name)

            if tool_fn is None:
                results.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "name": tool_name,
                        "content": f"Error: Tool '{tool_name}' not found",
                    }
                )
                continue

            try:
                tool_args = tc.get("args", {})
                if callable(tool_fn):
                    output = tool_fn(**tool_args)
                else:
                    output = str(tool_fn)

                results.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "name": tool_name,
                        "content": str(output),
                    }
                )
            except Exception as e:
                results.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "name": tool_name,
                        "content": f"Error executing {tool_name}: {e}",
                    }
                )

        if results:
            return MiddlewareResult(state={"messages": messages + results})

        return None


# ── PermissionsMiddleware ────────────────────────────────────────────────


class PermissionsMiddleware(AgentMiddleware[Any]):
    """Enforces filesystem permission rules (allow/deny/interrupt).

    Checks every tool call against the configured permission rules.
    If a matching tool call targets a denied path, execution is halted.
    """

    name = "permissions"

    def __init__(
        self,
        permissions: list[FilesystemPermission] | None = None,
    ) -> None:
        super().__init__()
        self._permissions = permissions or []

    def before_agent(
        self,
        state: dict[str, Any],
        runtime: Any,
        config: MiddlewareConfig,
    ) -> MiddlewareResult | None:
        """Inject permission rules into state."""
        state["_permissions_rules"] = [
            {"path": p.path, "action": p.action.name.lower(), "description": p.description}
            for p in self._permissions
        ]
        return None

    def after_agent(
        self,
        state: dict[str, Any],
        runtime: Any,
        config: MiddlewareConfig,
    ) -> MiddlewareResult | None:
        """Check tool call paths against permission rules."""
        messages = state.get("messages", [])
        if not messages:
            return None

        last = messages[-1]
        if not isinstance(last, dict) or last.get("role") != "assistant":
            return None

        tool_calls = last.get("tool_calls", [])
        for tc in tool_calls:
            args = tc.get("args", {})
            # Check path arguments
            for key in ("path", "file_path", "directory", "source", "destination"):
                path_val = args.get(key)
                if path_val and isinstance(path_val, str):
                    result = self._check_permission(path_val)
                    if result == PermissionAction.DENY:
                        return MiddlewareResult(
                            state={
                                "messages": messages
                                + [
                                    {
                                        "role": "tool",
                                        "tool_call_id": tc.get("id", ""),
                                        "name": tc.get("name", ""),
                                        "content": f"Permission denied: access to '{path_val}' is not allowed.",
                                    }
                                ],
                            }
                        )
                    elif result == PermissionAction.INTERRUPT:
                        return MiddlewareResult(
                            state={
                                "messages": messages
                                + [
                                    {
                                        "role": "tool",
                                        "tool_call_id": tc.get("id", ""),
                                        "name": tc.get("name", ""),
                                        "content": f"Approval required: access to '{path_val}' needs human approval.",
                                    }
                                ],
                            }
                        )

        return None

    def _check_permission(self, path: str) -> PermissionAction | None:
        """Check a path against permission rules.

        Args:
            path: The path to check.

        Returns:
            The matching action, or None (allow by default).
        """
        for perm in self._permissions:
            if self._path_matches(path, perm.path):
                return perm.action
        return None

    def _path_matches(self, path: str, pattern: str) -> bool:
        """Check if a path matches a permission pattern.

        Supports:
        - Exact match
        - Prefix match (trailing /)
        - Glob-style (*)

        Args:
            path: The actual path.
            pattern: The permission pattern.

        Returns:
            True if the path matches.
        """
        if pattern.endswith("*"):
            return path.startswith(pattern[:-1])
        if pattern.endswith("/"):
            return path.startswith(pattern)
        return path == pattern


# ── ToolExclusionMiddleware ──────────────────────────────────────────────


class ToolExclusionMiddleware(AgentMiddleware[Any]):
    """Removes excluded tools from the set of available tools.

    Supports HarnessProfile excluded_tools configuration.
    """

    name = "tool_exclusion"

    def __init__(
        self,
        excluded_tools: list[str] | None = None,
    ) -> None:
        super().__init__()
        self._excluded = set(excluded_tools or [])

    def before_agent(
        self,
        state: dict[str, Any],
        runtime: Any,
        config: MiddlewareConfig,
    ) -> MiddlewareResult | None:
        """Remove excluded tools from the available tool list."""
        available = state.get("_available_tools", [])
        filtered = [t for t in available if t not in self._excluded]
        state["_available_tools"] = filtered
        state["_excluded_tools"] = list(self._excluded)
        return None

    def modify_request(self, request: ModelRequest) -> ModelRequest:
        """Filter excluded tools from the model request."""
        request.tools = [
            t for t in request.tools
            if (getattr(t, "name", None) or str(t)) not in self._excluded
        ]
        return request


# ── ToolCallLimitMiddleware ──────────────────────────────────────────────


class ToolCallLimitMiddleware(AgentMiddleware[Any]):
    """Limits the number of tool calls the model can make per turn.

    Prevents runaway tool calling and excessive token usage.
    """

    name = "tool_call_limit"

    def __init__(
        self,
        max_calls_per_turn: int = 20,
    ) -> None:
        super().__init__()
        self._max_calls = max_calls_per_turn

    def before_agent(
        self,
        state: dict[str, Any],
        runtime: Any,
        config: MiddlewareConfig,
    ) -> MiddlewareResult | None:
        """Inject tool call limit into state."""
        state["_tool_call_limit"] = self._max_calls
        state["_tool_call_count"] = 0
        return None

    def after_agent(
        self,
        state: dict[str, Any],
        runtime: Any,
        config: MiddlewareConfig,
    ) -> MiddlewareResult | None:
        """Count tool calls and halt if limit exceeded."""
        messages = state.get("messages", [])
        if not messages:
            return None

        last = messages[-1]
        if not isinstance(last, dict):
            return None

        tool_calls = last.get("tool_calls", [])
        call_count = state.get("_tool_call_count", 0) + len(tool_calls)
        state["_tool_call_count"] = call_count

        if call_count > self._max_calls:
            return MiddlewareResult(
                state={
                    "messages": messages
                    + [
                        {
                            "role": "tool",
                            "tool_call_id": "__limit__",
                            "name": "__tool_call_limit__",
                            "content": (
                                f"Tool call limit ({self._max_calls}) exceeded. "
                                f"You made {call_count} tool calls this turn. "
                                "Please summarize your results."
                            ),
                        }
                    ],
                }
            )

        return None


# ── ToolSelectionMiddleware ──────────────────────────────────────────────


class ToolSelectionMiddleware(AgentMiddleware[Any]):
    """Filters available tools based on the current conversation context.

    Removes tools that are not relevant to the current task, reducing the
    tool set size for better model focus and lower token usage.
    """

    name = "tool_selection"

    def __init__(self) -> None:
        super().__init__()

    def before_agent(
        self,
        state: dict[str, Any],
        runtime: Any,
        config: MiddlewareConfig,
    ) -> MiddlewareResult | None:
        """Select relevant tools based on context."""
        return None

    def modify_request(self, request: ModelRequest) -> ModelRequest:
        """Filter tools in the request.

        In a full implementation, this would use LLM-based selection or
        keyword matching.  For now, we pass all tools through.
        """
        # Placeholder: pass through
        return request


__all__ = [
    "FilesystemPermission",
    "PatchToolCallsMiddleware",
    "PermissionAction",
    "PermissionsMiddleware",
    "ToolCall",
    "ToolCallLimitMiddleware",
    "ToolExclusionMiddleware",
    "ToolSelectionMiddleware",
    "ToolingMiddleware",
]