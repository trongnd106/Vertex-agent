"""Built-in filesystem tools for the agent.

Provides read/write/edit/delete/search operations on the filesystem with
permission integration, large-result eviction, and interrupt support.

Inspired by DeepAgents' ``middleware/filesystem.py`` and
orchestrator's file tool patterns.

Permission model:
    Each filesystem tool checks permissions via ``FilesystemPermission`` rules
    before executing.  Operations can be allowed, denied, or interrupted
    (human-in-the-loop).
"""

from __future__ import annotations

import fnmatch
import os
import re
import subprocess  # noqa: S404 — controlled via backend permissions
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Maximum result size before offloading (20K tokens ≈ 80K chars)
MAX_RESULT_CHARS = 80_000


# ── Result types ─────────────────────────────────────────────────────────


@dataclass
class ToolResult:
    """Standard result for a tool execution."""

    success: bool
    """Whether the tool executed successfully."""
    data: Any = None
    """Result data (string, list, dict, etc.)."""
    error: str = ""
    """Error message if not successful."""
    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional metadata (timing, eviction, etc.)."""
    evicted: bool = False
    """Whether the result was offloaded due to size."""


# ── Permission integration ───────────────────────────────────────────────


@dataclass
class FilePermission:
    """Permission rule for filesystem operations."""

    paths: list[str] = field(default_factory=lambda: ["*"])
    """Glob patterns of allowed/denied paths."""
    operations: list[str] = field(default_factory=lambda: ["read", "write", "delete", "execute"])
    """Which operations this permission applies to."""
    mode: str = "allow"
    """``allow``, ``deny``, or ``interrupt``."""


def _check_permission(
    path: str,
    operation: str,
    permissions: list[FilePermission] | None,
) -> tuple[bool, str]:
    """Check if an operation on a path is allowed.

    Args:
        path: File path to check.
        operation: Operation name (read, write, delete, execute).
        permissions: List of permission rules.

    Returns:
        ``(allowed, reason)`` — if ``allowed`` is False, ``reason`` explains why.
    """
    if not permissions:
        return True, ""

    path_obj = Path(path).resolve()

    for perm in permissions:
        if operation not in perm.operations:
            continue
        for pattern in perm.paths:
            if fnmatch.fnmatch(str(path_obj), pattern):
                if perm.mode == "deny":
                    return False, f"Permission denied: {operation} on {path}"
                elif perm.mode == "interrupt":
                    return False, f"Interrupt required: {operation} on {path}"
                # allow — continue to check other rules
                break

    return True, ""


def _evict_if_large(result: str) -> ToolResult:
    """Evict result if it exceeds the size limit.

    Args:
        result: The result string.

    Returns:
        ToolResult with data or eviction marker.
    """
    if len(result) > MAX_RESULT_CHARS:
        preview = result[:200]
        return ToolResult(
            success=True,
            data=f"[Large result evicted: {len(result)} chars. Preview: {preview}...]",
            evicted=True,
            metadata={"original_size": len(result)},
        )
    return ToolResult(success=True, data=result)


# ── Filesystem tools ─────────────────────────────────────────────────────

# Each tool is a standalone function that returns a ToolResult.
# They accept an optional ``permissions`` kwarg for access control.


def ls(
    path: str = ".",
    permissions: list[FilePermission] | None = None,
) -> ToolResult:
    """List directory contents.

    Args:
        path: Directory path to list.
        permissions: Permission rules.

    Returns:
        ``ToolResult`` with list of file entries.
    """
    allowed, reason = _check_permission(path, "read", permissions)
    if not allowed:
        return ToolResult(success=False, error=reason)

    try:
        p = Path(path).resolve()
        if not p.exists():
            return ToolResult(success=False, error=f"Path does not exist: {path}")
        if not p.is_dir():
            return ToolResult(success=False, error=f"Not a directory: {path}")

        entries: list[dict[str, Any]] = []
        for entry in sorted(p.iterdir()):
            try:
                stat = entry.stat()
                entries.append({
                    "name": entry.name,
                    "type": "directory" if entry.is_dir() else "file",
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                })
            except OSError:
                entries.append({
                    "name": entry.name,
                    "type": "unknown",
                })

        return ToolResult(success=True, data=entries)
    except PermissionError as e:
        return ToolResult(success=False, error=f"Permission denied: {e}")
    except OSError as e:
        return ToolResult(success=False, error=f"OS error: {e}")


def read_file(
    path: str,
    offset: int | None = None,
    limit: int | None = None,
    permissions: list[FilePermission] | None = None,
) -> ToolResult:
    """Read file contents with optional offset and limit.

    Args:
        path: File path to read.
        offset: Line offset to start reading from (0-indexed).
        limit: Maximum number of lines to read.
        permissions: Permission rules.

    Returns:
        ``ToolResult`` with file content.
    """
    allowed, reason = _check_permission(path, "read", permissions)
    if not allowed:
        return ToolResult(success=False, error=reason)

    try:
        p = Path(path).resolve()
        if not p.exists():
            return ToolResult(success=False, error=f"File does not exist: {path}")
        if not p.is_file():
            return ToolResult(success=False, error=f"Not a file: {path}")

        content = p.read_text(encoding="utf-8", errors="replace")

        if offset is not None or limit is not None:
            lines = content.splitlines(keepends=True)
            start = offset or 0
            end = start + (limit or len(lines))
            content = "".join(lines[start:end])

        return _evict_if_large(content)
    except PermissionError as e:
        return ToolResult(success=False, error=f"Permission denied: {e}")
    except OSError as e:
        return ToolResult(success=False, error=f"OS error: {e}")


def write_file(
    path: str,
    content: str,
    permissions: list[FilePermission] | None = None,
) -> ToolResult:
    """Write content to a file (create or overwrite).

    Args:
        path: File path to write.
        content: Text content to write.
        permissions: Permission rules.

    Returns:
        ``ToolResult`` with confirmation.
    """
    allowed, reason = _check_permission(path, "write", permissions)
    if not allowed:
        return ToolResult(success=False, error=reason)

    try:
        p = Path(path).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return ToolResult(
            success=True,
            data=f"Written {len(content)} chars to {path}",
            metadata={"size": len(content)},
        )
    except PermissionError as e:
        return ToolResult(success=False, error=f"Permission denied: {e}")
    except OSError as e:
        return ToolResult(success=False, error=f"OS error: {e}")


def edit_file(
    path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
    permissions: list[FilePermission] | None = None,
) -> ToolResult:
    """Edit a file by replacing text (find & replace).

    Args:
        path: File path to edit.
        old_string: Text to find.
        new_string: Text to replace with.
        replace_all: Replace all occurrences (default: replace first).
        permissions: Permission rules.

    Returns:
        ``ToolResult`` with replacement count.
    """
    allowed, reason = _check_permission(path, "write", permissions)
    if not allowed:
        return ToolResult(success=False, error=reason)

    try:
        p = Path(path).resolve()
        if not p.exists():
            return ToolResult(success=False, error=f"File does not exist: {path}")

        content = p.read_text(encoding="utf-8")
        if replace_all:
            count = content.count(old_string)
            if count == 0:
                return ToolResult(success=False, error=f"String not found: {old_string[:50]}")
            new_content = content.replace(old_string, new_string)
        else:
            count = content.count(old_string)
            if count == 0:
                return ToolResult(success=False, error=f"String not found: {old_string[:50]}")
            new_content = content.replace(old_string, new_string, 1)

        p.write_text(new_content, encoding="utf-8")
        return ToolResult(
            success=True,
            data=f"Replaced {count} occurrence(s) in {path}",
            metadata={"replacements": count},
        )
    except PermissionError as e:
        return ToolResult(success=False, error=f"Permission denied: {e}")
    except OSError as e:
        return ToolResult(success=False, error=f"OS error: {e}")


def delete_file(
    path: str,
    permissions: list[FilePermission] | None = None,
) -> ToolResult:
    """Delete a file or empty directory.

    Args:
        path: Path to delete.
        permissions: Permission rules.

    Returns:
        ``ToolResult`` with confirmation.
    """
    allowed, reason = _check_permission(path, "delete", permissions)
    if not allowed:
        return ToolResult(success=False, error=reason)

    try:
        p = Path(path).resolve()
        if not p.exists():
            return ToolResult(success=False, error=f"Path does not exist: {path}")
        if p.is_dir():
            # Only delete empty directories (safety)
            try:
                p.rmdir()
            except OSError:
                return ToolResult(
                    success=False,
                    error=f"Directory not empty: {path}. Use recursive deletion cautiously.",
                )
        else:
            p.unlink()
        return ToolResult(success=True, data=f"Deleted: {path}")
    except PermissionError as e:
        return ToolResult(success=False, error=f"Permission denied: {e}")
    except OSError as e:
        return ToolResult(success=False, error=f"OS error: {e}")


def glob_files(
    pattern: str,
    root: str = ".",
    permissions: list[FilePermission] | None = None,
) -> ToolResult:
    """Find files matching a glob pattern.

    Args:
        pattern: Glob pattern (e.g. ``**/*.py``).
        root: Root directory to search from.
        permissions: Permission rules.

    Returns:
        ``ToolResult`` with matching file paths.
    """
    allowed, reason = _check_permission(root, "read", permissions)
    if not allowed:
        return ToolResult(success=False, error=reason)

    try:
        matches = list(Path(root).resolve().rglob(pattern))
        result = [str(m.relative_to(Path(root).resolve())) for m in sorted(matches) if m.is_file()]
        return _evict_if_large("\n".join(result))
    except PermissionError as e:
        return ToolResult(success=False, error=f"Permission denied: {e}")
    except OSError as e:
        return ToolResult(success=False, error=f"OS error: {e}")


def grep_files(
    pattern: str,
    path: str = ".",
    include: str | None = None,
    permissions: list[FilePermission] | None = None,
) -> ToolResult:
    """Search for a pattern in files.

    Args:
        pattern: Regex pattern to search for.
        path: File or directory to search.
        include: Optional glob pattern to filter files (e.g. ``*.py``).
        permissions: Permission rules.

    Returns:
        ``ToolResult`` with matching lines.
    """
    allowed, reason = _check_permission(path, "read", permissions)
    if not allowed:
        return ToolResult(success=False, error=reason)

    try:
        search_path = Path(path).resolve()
        matches: list[str] = []

        if search_path.is_file():
            files = [search_path]
        else:
            files = list(search_path.rglob(include or "*"))
            files = [f for f in files if f.is_file()]

        compiled = re.compile(pattern)

        for file_path in files:
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
                for i, line in enumerate(content.splitlines(), 1):
                    if compiled.search(line):
                        rel = os.path.relpath(str(file_path))
                        matches.append(f"{rel}:{i}: {line.rstrip()[:200]}")
            except (PermissionError, OSError):
                continue

        if not matches:
            return ToolResult(success=True, data="No matches found")

        return _evict_if_large("\n".join(matches))
    except re.error as e:
        return ToolResult(success=False, error=f"Invalid regex: {e}")
    except OSError as e:
        return ToolResult(success=False, error=f"OS error: {e}")


def execute_command(
    command: str,
    cwd: str | None = None,
    timeout: float = 30.0,
    permissions: list[FilePermission] | None = None,
) -> ToolResult:
    """Execute a shell command.

    .. caution::
        This tool is available only when the backend explicitly enables it
        and permissions allow.  Security-checked via permission rules.

    Args:
        command: Shell command to execute.
        cwd: Working directory (default: current dir).
        timeout: Timeout in seconds.
        permissions: Permission rules.

    Returns:
        ``ToolResult`` with stdout, stderr, and exit code.
    """
    allowed, reason = _check_permission(".", "execute", permissions)
    if not allowed:
        return ToolResult(success=False, error=reason)

    try:
        result = subprocess.run(  # noqa: S602 — gated by permissions
            command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=cwd or os.getcwd(),
            timeout=timeout,
        )
        output_parts: list[str] = []
        if result.stdout:
            output_parts.append(result.stdout)
        if result.stderr:
            output_parts.append(f"stderr:\n{result.stderr}")

        data = "\n".join(output_parts) if output_parts else "(no output)"

        tool_result = ToolResult(
            success=result.returncode == 0,
            data=data,
            metadata={
                "returncode": result.returncode,
                "command": command[:200],
            },
        )
        if len(data) > MAX_RESULT_CHARS:
            tool_result.evicted = True
        return tool_result
    except subprocess.TimeoutExpired:
        return ToolResult(success=False, error=f"Command timed out after {timeout}s")
    except OSError as e:
        return ToolResult(success=False, error=f"OS error: {e}")


# ── Tool registry ────────────────────────────────────────────────────────

FILESYSTEM_TOOLS: dict[str, dict[str, Any]] = {
    "ls": {
        "name": "ls",
        "description": "List directory contents. Returns file names, types, sizes, and modification times.",
        "fn": ls,
        "category": "filesystem",
        "permission_operations": ["read"],
    },
    "read_file": {
        "name": "read_file",
        "description": "Read the contents of a file. Supports offset and limit for partial reads.",
        "fn": read_file,
        "category": "filesystem",
        "permission_operations": ["read"],
    },
    "write_file": {
        "name": "write_file",
        "description": "Write content to a file. Creates parent directories if needed. Overwrites existing files.",
        "fn": write_file,
        "category": "filesystem",
        "permission_operations": ["write"],
    },
    "edit_file": {
        "name": "edit_file",
        "description": "Edit a file by finding and replacing text. Supports single or all-occurrence replacement.",
        "fn": edit_file,
        "category": "filesystem",
        "permission_operations": ["write"],
    },
    "delete": {
        "name": "delete",
        "description": "Delete a file or empty directory. Will not delete non-empty directories.",
        "fn": delete_file,
        "category": "filesystem",
        "permission_operations": ["delete"],
    },
    "glob": {
        "name": "glob",
        "description": "Find files matching a glob pattern (e.g. '**/*.py'). Searches recursively from root.",
        "fn": glob_files,
        "category": "filesystem",
        "permission_operations": ["read"],
    },
    "grep": {
        "name": "grep",
        "description": "Search for a regex pattern in files. Supports filtering by file extension.",
        "fn": grep_files,
        "category": "filesystem",
        "permission_operations": ["read"],
    },
    "execute": {
        "name": "execute",
        "description": "Execute a shell command. Available only when sandbox/backend supports it.",
        "fn": execute_command,
        "category": "filesystem",
        "permission_operations": ["execute"],
    },
}


__all__ = [
    "FILESYSTEM_TOOLS",
    "FilePermission",
    "ToolResult",
    "delete_file",
    "edit_file",
    "execute_command",
    "glob_files",
    "grep_files",
    "ls",
    "read_file",
    "write_file",
]