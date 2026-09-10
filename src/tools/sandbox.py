"""Sandbox and safe execution environment.

Provides isolation layers for executing untrusted code and commands:
- ``BaseSandbox`` abstract base
- ``LocalShellSandbox`` — subprocess with resource limits
- ``PythonSandbox`` — restricted Python execution via ``eval``/``exec`` with
  built-in and import whitelists
- ``DockerSandbox`` — container-level isolation (requires ``docker``)

Each sandbox enforces resource limits (timeout, memory, output size) and
returns structured ``SandboxResult``.
"""

from __future__ import annotations

import builtins
import io
import os
import resource
import shlex
import signal
import subprocess
import sys
import tempfile
import threading
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from src.tools.filesystem import ToolResult


# ── Resource limits ─────────────────────────────────────────────────────


@dataclass
class ResourceLimits:
    """Resource constraints for sandboxed execution."""

    timeout: float = 30.0
    """Max wall-clock time in seconds."""
    max_output_chars: int = 80_000
    """Max characters in stdout/stderr."""
    max_memory_mb: int = 512
    """Max memory in MB (process-level on Linux)."""
    max_processes: int = 64
    """Max child processes (RLIMIT_NPROC on Linux)."""
    work_dir: str | None = None
    """Working directory. Falls back to temp dir if None."""


# ── Result ──────────────────────────────────────────────────────────────


@dataclass
class SandboxResult:
    """Structured result from a sandboxed execution."""

    success: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    timed_out: bool = False
    resource_violation: bool = False
    error: str = ""


# ── Base sandbox ────────────────────────────────────────────────────────


class BaseSandbox(ABC):
    """Abstract base for sandbox implementations."""

    def __init__(self, limits: ResourceLimits | None = None) -> None:
        self.limits = limits or ResourceLimits()

    @abstractmethod
    def run(self, command: str, cwd: str | None = None) -> SandboxResult:
        """Execute a command in the sandbox.

        Args:
            command: Command to execute.
            cwd: Working directory override.

        Returns:
            ``SandboxResult``.
        """
        ...

    @abstractmethod
    def check_supported(self) -> bool:
        """Check if this sandbox backend is available on the current system."""
        ...


# ── Local shell sandbox ─────────────────────────────────────────────────


class LocalShellSandbox(BaseSandbox):
    """Sandbox that runs commands as a local subprocess with resource limits.

    Applies ``resource.setrlimit`` for memory and process limits on Linux.
    """

    def run(self, command: str, cwd: str | None = None) -> SandboxResult:
        target_cwd = cwd or self.limits.work_dir
        timed_out = False
        resource_violation = False

        try:
            proc = subprocess.Popen(
                command,
                shell=True,  # noqa: S602
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=_set_resource_limits(self.limits) if sys.platform == "linux" else None,
                cwd=target_cwd,
            )

            try:
                stdout_bytes, stderr_bytes = proc.communicate(timeout=self.limits.timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout_bytes, stderr_bytes = proc.communicate(timeout=5)
                timed_out = True

            stdout = stdout_bytes.decode("utf-8", errors="replace")[: self.limits.max_output_chars]
            stderr = stderr_bytes.decode("utf-8", errors="replace")[: self.limits.max_output_chars]

            return SandboxResult(
                success=proc.returncode == 0 and not timed_out,
                stdout=stdout,
                stderr=stderr,
                exit_code=proc.returncode or -1,
                timed_out=timed_out,
                resource_violation=resource_violation,
            )

        except OSError as e:
            return SandboxResult(success=False, exit_code=-1, error=str(e))

    def check_supported(self) -> bool:
        return True


def _set_resource_limits(limits: ResourceLimits) -> Callable[[], None]:
    """Return a preexec function that sets resource limits on the child process."""

    def _set() -> None:
        try:
            if limits.max_memory_mb > 0:
                mem_bytes = limits.max_memory_mb * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
            if limits.max_processes > 0:
                resource.setrlimit(
                    resource.RLIMIT_NPROC,
                    (limits.max_processes, limits.max_processes),
                )
        except (ValueError, resource.error):
            pass

    return _set


# ── Python sandbox ──────────────────────────────────────────────────────


# Whitelists for restricted Python execution
PYTHON_BUILTIN_WHITELIST = frozenset({
    "abs", "all", "any", "ascii", "bool", "bytes", "chr", "complex",
    "dict", "divmod", "enumerate", "filter", "float", "format", "frozenset",
    "hex", "int", "isinstance", "iter", "len", "list", "map", "max", "min",
    "next", "oct", "ord", "pow", "range", "repr", "reversed", "round",
    "set", "slice", "sorted", "str", "sum", "tuple", "type", "zip",
})

IMPORT_WHITELIST = frozenset({
    "math", "json", "re", "datetime", "collections", "itertools",
    "functools", "random", "statistics", "decimal", " fractions",
    "typing", "enum", "string", "textwrap",
})


_safe_builtins_cache: dict[str, Any] | None = None


def _safe_builtins() -> dict[str, Any]:
    """Return a dict of safe builtins that only allows whitelisted imports."""
    global _safe_builtins_cache
    if _safe_builtins_cache is not None:
        return _safe_builtins_cache
    builtins_out: dict[str, Any] = {}
    src = __builtins__ if isinstance(__builtins__, dict) else __builtins__.__dict__
    for name in PYTHON_BUILTIN_WHITELIST:
        if name in src:
            builtins_out[name] = src[name]

    # Wrap __import__ to restrict by IMPORT_WHITELIST
    real_import = src.get("__import__", builtins.__import__)

    def _restricted_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name in IMPORT_WHITELIST or name.split(".")[0] in IMPORT_WHITELIST:
            return real_import(name, *args, **kwargs)
        raise ImportError(f"Module '{name}' is not allowed in sandbox")

    builtins_out["__import__"] = _restricted_import
    _safe_builtins_cache = builtins_out
    return builtins_out


class PythonSandbox(BaseSandbox):
    """Restricted Python execution sandbox.

    Executes Python code in an isolated namespace with:
    - Whitelisted builtins only
    - Whitelisted import modules only
    - Timeout via threading timer
    - Output capture
    """

    def run(self, command: str, cwd: str | None = None) -> SandboxResult:
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        result: dict[str, Any] = {"success": False, "error": ""}
        timed_out = False

        scope: dict[str, Any] = {
            "__name__": "__sandbox__",
            "__builtins__": _safe_builtins(),
        }
        def _exec() -> None:
            try:
                # Capture stdout/stderr
                old_stdout, old_stderr = sys.stdout, sys.stderr
                sys.stdout, sys.stderr = stdout_buf, stderr_buf
                try:
                    exec(command, scope)  # noqa: S102
                    result["success"] = True
                except Exception as e:
                    result["error"] = f"{type(e).__name__}: {e}"
                    result["success"] = False
                finally:
                    sys.stdout, sys.stderr = old_stdout, old_stderr
            except Exception as e:
                result["error"] = f"Sandbox internal: {e}"
                result["success"] = False

        thread = threading.Thread(target=_exec, daemon=True)
        thread.start()
        thread.join(timeout=self.limits.timeout)

        if thread.is_alive():
            timed_out = True
            result["success"] = False
            result["error"] = f"Execution timed out after {self.limits.timeout}s"

        stdout = stdout_buf.getvalue()[: self.limits.max_output_chars]
        stderr = stderr_buf.getvalue()[: self.limits.max_output_chars]

        return SandboxResult(
            success=result.get("success", False),
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            error=result.get("error", ""),
        )

    def check_supported(self) -> bool:
        return True


# ── Docker sandbox ──────────────────────────────────────────────────────


class DockerSandbox(BaseSandbox):
    """Container-level sandbox using Docker.

    Runs commands inside a specified Docker image with optional volumes,
    network disable, and resource limits passed as ``docker run`` flags.
    """

    def __init__(
        self,
        image: str = "python:3.10-slim",
        limits: ResourceLimits | None = None,
        volumes: list[tuple[str, str]] | None = None,
        network_disabled: bool = True,
        remove_after: bool = True,
    ) -> None:
        super().__init__(limits)
        self.image = image
        self.volumes = volumes or []
        self.network_disabled = network_disabled
        self.remove_after = remove_after

    def run(self, command: str, cwd: str | None = None) -> SandboxResult:
        docker_args = [
            "docker",
            "run",
            "--rm" if self.remove_after else "",
            "--network", "none" if self.network_disabled else "bridge",
            "-i",
            "--stop-timeout", str(int(self.limits.timeout)),
        ]

        if self.limits.max_memory_mb > 0:
            docker_args.extend(["--memory", f"{self.limits.max_memory_mb}m"])

        for host_path, container_path in self.volumes:
            docker_args.extend(["-v", f"{host_path}:{container_path}"])

        docker_args.append(self.image)
        docker_args.extend(["/bin/sh", "-c", command])

        try:
            proc = subprocess.Popen(
                [arg for arg in docker_args if arg],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd or self.limits.work_dir,
            )
            try:
                stdout_bytes, stderr_bytes = proc.communicate(timeout=self.limits.timeout + 10)
                timed_out = False
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout_bytes, stderr_bytes = proc.communicate(timeout=5)
                timed_out = True

            stdout = stdout_bytes.decode("utf-8", errors="replace")[: self.limits.max_output_chars]
            stderr = stderr_bytes.decode("utf-8", errors="replace")[: self.limits.max_output_chars]

            return SandboxResult(
                success=proc.returncode == 0 and not timed_out,
                stdout=stdout,
                stderr=stderr,
                exit_code=proc.returncode or -1,
                timed_out=timed_out,
            )

        except FileNotFoundError:
            return SandboxResult(
                success=False,
                error="Docker not found. Install Docker or use LocalShellSandbox.",
            )
        except OSError as e:
            return SandboxResult(success=False, exit_code=-1, error=str(e))

    def check_supported(self) -> bool:
        try:
            result = subprocess.run(
                ["docker", "--version"],
                capture_output=True,
                timeout=10,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False


__all__ = [
    "BaseSandbox",
    "DockerSandbox",
    "LocalShellSandbox",
    "PythonSandbox",
    "ResourceLimits",
    "SandboxResult",
]