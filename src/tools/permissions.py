"""Tool permission, role-based access control, audit logging, and HITL.

Provides:
- ``FilesystemPermission`` — path-level allow/deny/interrupt rules
- ``Role`` and ``RoleBasedAccess`` — role ↔ allowed tools mapping
- ``HumanInTheLoop`` — confirm/deny workflow for interrupt-mode operations
- ``AuditLog`` — persistent audit trail of tool invocations
"""

from __future__ import annotations

import fnmatch
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from src.tools.filesystem import ToolResult

logger = logging.getLogger(__name__)


# ── Permission modes ────────────────────────────────────────────────────


class PermissionMode(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    INTERRUPT = "interrupt"


# ── Filesystem permission ───────────────────────────────────────────────


@dataclass
class FilesystemPermission:
    """Permission rule for filesystem paths.

    ``match_mode`` controls how ``path_pattern`` is matched:
    - ``exact`` — exact string comparison
    - ``prefix`` — path starts with pattern
    - ``glob`` — shell-style glob pattern
    """

    path_pattern: str
    """Path pattern to match."""
    mode: PermissionMode = PermissionMode.ALLOW
    """What to do when this rule matches."""
    operations: list[str] = field(default_factory=lambda: ["read", "write", "delete", "execute"])
    """Which operations this rule governs."""
    match_mode: str = "glob"
    """``exact``, ``prefix``, or ``glob``."""
    reason: str = ""
    """Reason recorded in audit when this rule fires."""

    def matches(self, path: str, operation: str) -> bool:
        """Check if a path+operation matches this rule.

        Args:
            path: Path to check.
            operation: Operation name.

        Returns:
            True if this rule applies.
        """
        if operation not in self.operations:
            return False

        if self.match_mode == "exact":
            return path == self.path_pattern
        elif self.match_mode == "prefix":
            return str(Path(path).resolve()).startswith(str(Path(self.path_pattern).resolve()))
        elif self.match_mode == "glob":
            return fnmatch.fnmatch(str(Path(path).resolve()), self.path_pattern)

        return False


# ── Role-based access control ───────────────────────────────────────────


@dataclass
class Role:
    """A named role with associated permissions."""

    name: str
    description: str = ""
    allowed_tools: list[str] = field(default_factory=lambda: ["*"])
    """Glob patterns of tool names this role can use. ``*`` means all."""
    filesystem_permissions: list[FilesystemPermission] = field(default_factory=list)
    """Filesystem permission rules."""
    denied_tools: list[str] = field(default_factory=list)
    """Explicitly denied tool patterns (checked first)."""
    max_calls_per_turn: int = 0
    """0 = unlimited."""


class RoleBasedAccess:
    """Role-based access control for tools."""

    def __init__(self) -> None:
        self._roles: dict[str, Role] = {}
        self._lock = threading.Lock()

    def add_role(self, role: Role) -> None:
        """Register a role."""
        with self._lock:
            self._roles[role.name] = role

    def remove_role(self, name: str) -> bool:
        """Remove a role.

        Returns:
            True if removed.
        """
        with self._lock:
            return self._roles.pop(name, None) is not None

    def get_role(self, name: str) -> Role | None:
        """Get a role by name."""
        return self._roles.get(name)

    def check_tool_allowed(self, role_name: str, tool_name: str) -> tuple[bool, str]:
        """Check if a role is allowed to use a tool.

        Returns:
            ``(allowed, reason)``.
        """
        role = self._roles.get(role_name)
        if role is None:
            return False, f"Unknown role: {role_name}"

        # Deny patterns checked first
        for deny_pattern in role.denied_tools:
            if deny_pattern == tool_name or fnmatch.fnmatch(tool_name, deny_pattern):
                return False, f"Tool '{tool_name}' denied by role '{role_name}'"

        # Allow patterns
        for allow_pattern in role.allowed_tools:
            if allow_pattern == "*" or fnmatch.fnmatch(tool_name, allow_pattern):
                return True, ""

        return False, f"Tool '{tool_name}' not in allowed list for role '{role_name}'"

    def check_filesystem(
        self,
        role_name: str,
        path: str,
        operation: str,
    ) -> tuple[bool, str]:
        """Check filesystem permission for a role.

        Returns:
            ``(allowed, reason)``.
        """
        role = self._roles.get(role_name)
        if role is None:
            return False, f"Unknown role: {role_name}"

        for perm in role.filesystem_permissions:
            if perm.matches(path, operation):
                if perm.mode == PermissionMode.DENY:
                    return False, perm.reason or f"Denied by rule: {perm.path_pattern}"
                elif perm.mode == PermissionMode.INTERRUPT:
                    return False, f"HITL required: {path}"
                break  # allow

        return True, ""


# ── Human-in-the-loop ───────────────────────────────────────────────────


class HITLDecision(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


@dataclass
class HITLRequest:
    """A request for human approval."""

    id: str = ""
    tool_name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    decision: HITLDecision = HITLDecision.PENDING
    created_at: float = 0.0
    decided_at: float = 0.0
    decided_by: str = ""


class HumanInTheLoop:
    """Manages human approval workflow for interrupt-mode operations."""

    def __init__(self, auto_approve: bool = False) -> None:
        self._requests: dict[str, HITLRequest] = {}
        self._lock = threading.Lock()
        self._auto_approve = auto_approve
        self._counter = 0

    def request_approval(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        reason: str = "",
    ) -> HITLRequest:
        """Create an approval request.

        If ``auto_approve`` is True, immediately approves.

        Returns:
            The ``HITLRequest`` (already approved if auto_approve).
        """
        with self._lock:
            self._counter += 1
            req_id = f"hitl_{self._counter}_{int(time.time())}"
            req = HITLRequest(
                id=req_id,
                tool_name=tool_name,
                arguments=arguments,
                reason=reason,
                created_at=time.time(),
            )
            if self._auto_approve:
                req.decision = HITLDecision.APPROVED
                req.decided_at = time.time()
                req.decided_by = "auto"
            self._requests[req_id] = req
            return req

    def approve(self, request_id: str, by: str = "user") -> bool:
        """Approve a pending request.

        Returns:
            True if found and approved.
        """
        with self._lock:
            req = self._requests.get(request_id)
            if req is None or req.decision != HITLDecision.PENDING:
                return False
            req.decision = HITLDecision.APPROVED
            req.decided_at = time.time()
            req.decided_by = by
            return True

    def deny(self, request_id: str, by: str = "user") -> bool:
        """Deny a pending request.

        Returns:
            True if found and denied.
        """
        with self._lock:
            req = self._requests.get(request_id)
            if req is None or req.decision != HITLDecision.PENDING:
                return False
            req.decision = HITLDecision.DENIED
            req.decided_at = time.time()
            req.decided_by = by
            return True

    def get_request(self, request_id: str) -> HITLRequest | None:
        """Get a request by ID."""
        return self._requests.get(request_id)

    def list_pending(self) -> list[HITLRequest]:
        """List all pending requests."""
        return [
            req for req in self._requests.values()
            if req.decision == HITLDecision.PENDING
        ]

    def wait_for_decision(
        self,
        request_id: str,
        poll_interval: float = 0.5,
        timeout: float = 300.0,
    ) -> HITLRequest:
        """Block until a decision is made.

        Args:
            request_id: Request ID.
            poll_interval: Seconds between polls.
            timeout: Max wait time.

        Returns:
            The updated request.

        Raises:
            TimeoutError: If no decision within timeout.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            req = self.get_request(request_id)
            if req and req.decision != HITLDecision.PENDING:
                return req
            time.sleep(poll_interval)
        raise TimeoutError(f"HITL decision timeout for {request_id}")


# ── Audit log ───────────────────────────────────────────────────────────


@dataclass
class AuditEntry:
    """A single audit log entry."""

    timestamp: float = 0.0
    tool_name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    result: str = ""
    success: bool = True
    duration_ms: float = 0.0
    role: str = ""
    user: str = ""
    permission_hit: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class AuditLog:
    """Thread-safe, append-only audit log for tool executions.

    Supports in-memory storage (default) and optional file persistence.
    The file is written as newline-delimited JSON (JSONL).
    """

    def __init__(self, file_path: str | None = None, max_entries: int = 10_000) -> None:
        self._entries: list[AuditEntry] = []
        self._lock = threading.Lock()
        self._file_path = file_path
        self._max_entries = max_entries

        if file_path:
            Path(file_path).parent.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        result: str = "",
        success: bool = True,
        duration_ms: float = 0.0,
        role: str = "",
        user: str = "",
        permission_hit: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> AuditEntry:
        """Record a tool execution in the audit log.

        Returns:
            The created ``AuditEntry``.
        """
        entry = AuditEntry(
            timestamp=time.time(),
            tool_name=tool_name,
            arguments=_sanitize_arguments(arguments),
            result=_truncate(result, 1000),
            success=success,
            duration_ms=duration_ms,
            role=role,
            user=user,
            permission_hit=permission_hit,
            metadata=metadata or {},
        )

        with self._lock:
            self._entries.append(entry)
            if len(self._entries) > self._max_entries:
                self._entries = self._entries[-self._max_entries:]
            if self._file_path:
                self._append_to_file(entry)

        return entry

    def query(
        self,
        tool_name: str | None = None,
        success: bool | None = None,
        role: str | None = None,
        limit: int = 100,
    ) -> list[AuditEntry]:
        """Query audit entries with optional filters.

        Args:
            tool_name: Filter by tool name.
            success: Filter by success status.
            role: Filter by role.
            limit: Max entries to return (most recent first).

        Returns:
            Matching entries.
        """
        with self._lock:
            entries = list(self._entries)

        if tool_name:
            entries = [e for e in entries if e.tool_name == tool_name]
        if success is not None:
            entries = [e for e in entries if e.success == success]
        if role:
            entries = [e for e in entries if e.role == role]

        return list(reversed(entries))[:limit]

    def get_stats(self) -> dict[str, Any]:
        """Get summary statistics from the audit log.

        Returns:
            Dict with counts, success rate, tool breakdown.
        """
        with self._lock:
            total = len(self._entries)
            if total == 0:
                return {"total": 0}
            succeeded = sum(1 for e in self._entries if e.success)
            tool_counts: dict[str, int] = {}
            for e in self._entries:
                tool_counts[e.tool_name] = tool_counts.get(e.tool_name, 0) + 1
            return {
                "total": total,
                "success_rate": succeeded / total if total > 0 else 0,
                "tool_counts": dict(sorted(tool_counts.items(), key=lambda x: -x[1])),
                "file_path": self._file_path,
            }

    def clear(self) -> None:
        """Clear all entries."""
        with self._lock:
            self._entries.clear()

    def _append_to_file(self, entry: AuditEntry) -> None:
        if not self._file_path:
            return
        try:
            with open(self._file_path, "a", encoding="utf-8") as f:
                f.write(_entry_to_json(entry) + "\n")
        except OSError as e:
            logger.warning("Failed to write audit log: %s", e)


def _sanitize_arguments(args: dict[str, Any]) -> dict[str, Any]:
    """Redact sensitive fields from audit entries (passwords, keys, tokens)."""
    sensitive_keys = {"password", "token", "api_key", "secret", "key", "authorization"}
    sanitized = {}
    for k, v in args.items():
        if any(s in k.lower() for s in sensitive_keys):
            sanitized[k] = "[REDACTED]"
        elif isinstance(v, str) and len(v) > 500:
            sanitized[k] = v[:500] + "...[truncated]"
        else:
            sanitized[k] = v
    return sanitized


def _truncate(text: str, max_len: int = 1000) -> str:
    return text if len(text) <= max_len else text[:max_len] + "...[truncated]"


def _entry_to_json(entry: AuditEntry) -> str:
    return json.dumps(entry.__dict__, default=str, ensure_ascii=False)


__all__ = [
    "AuditEntry",
    "AuditLog",
    "FilesystemPermission",
    "HITLDecision",
    "HITLRequest",
    "HumanInTheLoop",
    "PermissionMode",
    "Role",
    "RoleBasedAccess",
]