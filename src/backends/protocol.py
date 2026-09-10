"""Backend protocol definitions and abstract base classes.

Provides:
- ``BackendProtocol`` — filesystem-like operations (ls, read, write, …)
- ``SandboxBackendProtocol`` — extends backend with execute
- ``BaseSandbox`` — sandbox for containerised execution
"""

from __future__ import annotations

import abc
import os
import time
from dataclasses import dataclass, field
from typing import Any


# ── File info ─────────────────────────────────────────────────────────


@dataclass
class FileInfo:
    """Metadata about a file or directory entry.

    Attributes:
        name: File name (not full path).
        path: Full path relative to backend root.
        size: File size in bytes, -1 for directories.
        modified: Last modification timestamp as float.
        is_dir: Whether this is a directory.
        permissions: Unix-style permission string (e.g. "rw-r--r--").
    """

    name: str = ""
    path: str = ""
    size: int = 0
    modified: float = 0.0
    is_dir: bool = False
    permissions: str = ""

    @property
    def modified_iso(self) -> str:
        """Return modified timestamp as ISO 8601 string."""
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.modified))


# ── BackendProtocol ───────────────────────────────────────────────────


@dataclass
class BackendResult:
    """Result of a backend operation.

    Attributes:
        success: Whether the operation succeeded.
        data: Payload data (varies by operation).
        error: Error message on failure.
        metadata: Extra operation-specific metadata.
    """

    success: bool = True
    data: Any = None
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class BackendProtocol(abc.ABC):
    """Abstract protocol for filesystem-like backend operations.

    All operations return ``BackendResult``. Subclasses override the
    ``_impl`` methods; callers use the public methods.
    """

    # ── Directory ─────────────────────────────────────────────────────

    @abc.abstractmethod
    def ls(self, path: str = "") -> BackendResult:
        """List directory contents.

        Args:
            path: Directory path relative to root.

        Returns:
            ``BackendResult`` with ``data`` being ``list[FileInfo]``.
        """

    # ── File operations ───────────────────────────────────────────────

    @abc.abstractmethod
    def read(self, path: str) -> BackendResult:
        """Read file contents.

        Args:
            path: File path relative to root.

        Returns:
            ``BackendResult`` with ``data`` being the file content as str.
        """

    @abc.abstractmethod
    def write(self, path: str, content: str) -> BackendResult:
        """Write content to a file (overwrite).

        Args:
            path: File path relative to root.
            content: String content to write.

        Returns:
            ``BackendResult`` with success indicator.
        """

    @abc.abstractmethod
    def edit(self, path: str, old: str, new: str) -> BackendResult:
        """Find-and-replace edit on a file.

        Args:
            path: File path relative to root.
            old: String to find.
            new: Replacement string.

        Returns:
            ``BackendResult`` with success indicator.
        """

    @abc.abstractmethod
    def delete(self, path: str) -> BackendResult:
        """Delete a file or directory.

        Args:
            path: Path relative to root.

        Returns:
            ``BackendResult`` with success indicator.
        """

    @abc.abstractmethod
    def glob(self, pattern: str) -> BackendResult:
        """Find files matching a glob pattern.

        Args:
            pattern: Glob pattern relative to root.

        Returns:
            ``BackendResult`` with ``data`` being ``list[str]`` of paths.
        """

    @abc.abstractmethod
    def grep(self, pattern: str, path: str = "") -> BackendResult:
        """Search file contents by regex pattern.

        Args:
            pattern: Regex pattern.
            path: Directory or file to search; empty for full root.

        Returns:
            ``BackendResult`` with ``data`` being ``list[dict]`` with
            keys ``file``, ``line``, ``content``.
        """

    # ── File transfer ─────────────────────────────────────────────────

    @abc.abstractmethod
    def download_files(self, paths: list[str]) -> BackendResult:
        """Download files and return their contents as a dict.

        Args:
            paths: List of file paths.

        Returns:
            ``BackendResult`` with ``data`` being ``dict[str, str]``
            mapping paths to content.
        """

    @abc.abstractmethod
    def upload_files(self, files: dict[str, str]) -> BackendResult:
        """Upload files (map of path → content).

        Args:
            files: Dict mapping file paths to their content.

        Returns:
            ``BackendResult`` with success indicator.
        """

    # ── Async counterparts ────────────────────────────────────────────

    async def als(self, path: str = "") -> BackendResult:
        """Async list directory."""
        return self.ls(path)

    async def aread(self, path: str) -> BackendResult:
        """Async read file."""
        return self.read(path)

    async def awrite(self, path: str, content: str) -> BackendResult:
        """Async write file."""
        return self.write(path, content)

    async def aedit(self, path: str, old: str, new: str) -> BackendResult:
        """Async edit file."""
        return self.edit(path, old, new)

    async def adelete(self, path: str) -> BackendResult:
        """Async delete file."""
        return self.delete(path)

    async def aglob(self, pattern: str) -> BackendResult:
        """Async glob."""
        return self.glob(pattern)

    async def agrep(self, pattern: str, path: str = "") -> BackendResult:
        """Async grep."""
        return self.grep(pattern, path)

    async def adownload_files(self, paths: list[str]) -> BackendResult:
        """Async download files."""
        return self.download_files(paths)

    async def aupload_files(self, files: dict[str, str]) -> BackendResult:
        """Async upload files."""
        return self.upload_files(files)


# ── SandboxBackendProtocol ────────────────────────────────────────────


class SandboxBackendProtocol(BackendProtocol, abc.ABC):
    """Backend protocol extended with command execution."""

    @abc.abstractmethod
    def execute(self, command: str, timeout: float = 30.0) -> BackendResult:
        """Execute a shell command.

        Args:
            command: Shell command string.
            timeout: Execution timeout in seconds.

        Returns:
            ``BackendResult`` with ``data`` being ``{"stdout": ...,
            "stderr": ..., "exit_code": ...}``.
        """

    async def aexecute(self, command: str, timeout: float = 30.0) -> BackendResult:
        """Async execute."""
        return self.execute(command, timeout)


# ── BaseSandbox ───────────────────────────────────────────────────────


class BaseSandbox(abc.ABC):
    """Abstract sandbox for containerised execution.

    A sandbox provides an isolated environment for running commands
    and transferring files.
    """

    @abc.abstractmethod
    def execute(self, command: str, timeout: float = 30.0) -> BackendResult:
        """Execute a command inside the sandbox.

        Args:
            command: Shell command.
            timeout: Execution timeout.

        Returns:
            ``BackendResult`` with execution output.
        """

    @abc.abstractmethod
    def upload_files(self, files: dict[str, str]) -> BackendResult:
        """Upload files into the sandbox.

        Args:
            files: Dict mapping paths to content.
        """

    @abc.abstractmethod
    def download_files(self, paths: list[str]) -> BackendResult:
        """Download files from the sandbox.

        Args:
            paths: File paths inside the sandbox.

        Returns:
            ``BackendResult`` with ``data`` being ``dict[str, str]``.
        """

    @property
    @abc.abstractmethod
    def id(self) -> str:
        """Unique identifier for this sandbox instance."""


__all__ = [
    "BackendProtocol",
    "BackendResult",
    "BaseSandbox",
    "FileInfo",
    "SandboxBackendProtocol",
]