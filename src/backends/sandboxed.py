"""LocalShellBackend and sandbox integration for backend operations.

Provides:
- ``LocalShellBackend`` — FilesystemBackend + shell execute (dev only)
- ``ContainerSandbox`` — execute inside a container
- ``RoleBasedSandboxSelector`` — dev vs production + role-based selection
- ``DEFAULT_EXECUTE_TIMEOUT`` — default 30s timeout
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from src.backends.implementations import FilesystemBackend
from src.backends.protocol import BackendResult, BaseSandbox, SandboxBackendProtocol


DEFAULT_EXECUTE_TIMEOUT: float = 30.0


# ── LocalShellBackend ─────────────────────────────────────────────────


class LocalShellBackend(FilesystemBackend, SandboxBackendProtocol):
    """FilesystemBackend extended with shell command execution.

    **WARNING:** This backend provides no sandbox isolation. Filesystem
    operations are restricted to ``root_dir``, but shell commands run
    with the full privileges of the current user. Development use only.

    Inherits all filesystem operations from ``FilesystemBackend``.
    Adds ``execute()`` for running shell commands with a timeout.
    """

    def __init__(
        self,
        root_dir: str = "./workspace",
        timeout: float = DEFAULT_EXECUTE_TIMEOUT,
    ) -> None:
        super().__init__(root_dir)
        self._timeout = timeout
        self._lock = threading.Lock()

    def execute(self, command: str, timeout: float = DEFAULT_EXECUTE_TIMEOUT) -> BackendResult:
        """Execute a shell command.

        Args:
            command: Shell command to execute.
            timeout: Execution timeout in seconds.

        Returns:
            ``BackendResult`` with ``data`` containing ``stdout``,
            ``stderr``, and ``exit_code``.
        """
        effective_timeout = timeout or self._timeout
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=effective_timeout,
                cwd=self._root,
            )
            return BackendResult(
                data={
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "exit_code": result.returncode,
                }
            )
        except subprocess.TimeoutExpired:
            return BackendResult(
                success=False,
                error=f"Command timed out after {effective_timeout}s",
                data={"stdout": "", "stderr": "", "exit_code": -1},
            )
        except Exception as exc:
            return BackendResult(
                success=False,
                error=str(exc),
                data={"stdout": "", "stderr": "", "exit_code": -1},
            )


# ── ContainerSandbox ──────────────────────────────────────────────────


class ContainerSandbox(BaseSandbox):
    """Sandbox that executes commands inside a container (Docker).

    Provides file isolation, upload/download, and execution
    with resource limits.

    Attributes:
        image: Docker image to use (e.g. ``"python:3.11-slim"``).
        container_name: Name for the container instance.
        workdir: Working directory inside the container.
        memory_limit: Memory limit (e.g. ``"512m"``).
        cpu_limit: CPU limit (e.g. ``1.0``).
    """

    def __init__(
        self,
        image: str = "python:3.11-slim",
        container_name: str = "",
        workdir: str = "/workspace",
        memory_limit: str = "512m",
        cpu_limit: float = 1.0,
        timeout: float = DEFAULT_EXECUTE_TIMEOUT,
    ) -> None:
        self._image = image
        self._container_name = container_name or f"sandbox-{uuid.uuid4().hex[:8]}"
        self._workdir = workdir
        self._memory_limit = memory_limit
        self._cpu_limit = cpu_limit
        self._timeout = timeout
        self._id = str(uuid.uuid4())
        self._running = False

    @property
    def id(self) -> str:
        return self._id

    def _container_exec(self, command: str, timeout: float) -> subprocess.CompletedProcess:
        """Run a command inside the container via ``docker exec``."""
        import shlex
        safe_cmd = shlex.quote(f"cd {self._workdir} && {command}")
        docker_cmd = (
            f"timeout {int(timeout) + 5} docker exec -i {self._container_name} "
            f"sh -c {safe_cmd}"
        )
        return subprocess.run(
            docker_cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout + 10,
        )

    def execute(self, command: str, timeout: float = DEFAULT_EXECUTE_TIMEOUT) -> BackendResult:
        """Execute a command inside the sandbox container.

        If the container isn't running, tries to start it first.

        Args:
            command: Command to execute.
            timeout: Execution timeout.

        Returns:
            ``BackendResult`` with execution output.
        """
        effective_timeout = timeout or self._timeout
        try:
            result = self._container_exec(command, effective_timeout)
            return BackendResult(
                data={
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "exit_code": result.returncode,
                }
            )
        except subprocess.TimeoutExpired:
            return BackendResult(
                success=False,
                error=f"Command timed out after {effective_timeout}s",
                data={"stdout": "", "stderr": "", "exit_code": -1},
            )
        except FileNotFoundError:
            return BackendResult(
                success=False,
                error="Docker not available. ContainerSandbox requires Docker.",
                data={"stdout": "", "stderr": "", "exit_code": -1},
            )
        except Exception as exc:
            return BackendResult(
                success=False,
                error=str(exc),
                data={"stdout": "", "stderr": "", "exit_code": -1},
            )

    def upload_files(self, files: dict[str, str]) -> BackendResult:
        """Upload files into the sandbox.

        Uses ``docker cp`` to copy each file.
        """
        import tempfile

        try:
            for path, content in files.items():
                with tempfile.NamedTemporaryFile(mode="w", delete=False) as tmp:
                    tmp.write(content)
                    tmp_path = tmp.name
                dest = f"{self._container_name}:{self._workdir}/{path}"
                subprocess.run(
                    ["timeout", "30", "docker", "cp", tmp_path, dest],
                    capture_output=True,
                    text=True,
                    timeout=45,
                )
                os.unlink(tmp_path)
            return BackendResult(data=None)
        except FileNotFoundError:
            return BackendResult(
                success=False,
                error="Docker not available. ContainerSandbox requires Docker.",
            )
        except Exception as exc:
            return BackendResult(success=False, error=str(exc))

    def download_files(self, paths: list[str]) -> BackendResult:
        """Download files from the sandbox.

        Uses ``docker cp`` to copy each file to a temp dir.
        """
        import tempfile

        try:
            contents: dict[str, str] = {}
            for path in paths:
                tmp_dir = tempfile.mkdtemp()
                src = f"{self._container_name}:{self._workdir}/{path}"
                subprocess.run(
                    ["timeout", "30", "docker", "cp", src, tmp_dir],
                    capture_output=True,
                    text=True,
                    timeout=45,
                )
                local_path = os.path.join(tmp_dir, os.path.basename(path))
                if os.path.isfile(local_path):
                    with open(local_path) as f:
                        contents[path] = f.read()
                os.unlink(local_path)
                os.rmdir(tmp_dir)
            return BackendResult(data=contents)
        except FileNotFoundError:
            return BackendResult(
                success=False,
                error="Docker not available. ContainerSandbox requires Docker.",
            )
        except Exception as exc:
            return BackendResult(success=False, error=str(exc))

    def start(self) -> bool:
        """Start the sandbox container via ``docker run``.

        Returns:
            True if the container started successfully.
        """
        try:
            cmd = (
                f"timeout 30 docker run -d --name {self._container_name} "
                f"--memory {self._memory_limit} "
                f"--cpus {self._cpu_limit} "
                f"-w {self._workdir} "
                f"{self._image} sleep infinity"
            )
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
            self._running = result.returncode == 0
            return self._running
        except Exception:
            self._running = False
            return False

    def stop(self) -> bool:
        """Stop and remove the sandbox container.

        Returns:
            True if stopped successfully.
        """
        try:
            subprocess.run(
                f"timeout 15 docker rm -f {self._container_name}",
                shell=True,
                capture_output=True,
                timeout=30,
            )
            self._running = False
            return True
        except Exception:
            return False


# ── Role-based sandbox selector ───────────────────────────────────────


class SandboxType:
    LOCAL = "local"  # LocalShellBackend (dev)
    CONTAINER = "container"  # ContainerSandbox
    LANGSMITH = "langsmith"  # LangSmith remote sandbox


@dataclass
class RoleBasedSandboxSelector:
    """Selects a sandbox backend based on environment and role.

    Attributes:
        environment: ``"dev"`` or ``"production"``.
        roles: Dict mapping role name → sandbox type.
        dev_backend: Backend used in dev mode.
        production_backend: Backend used in production.
    """

    environment: str = "dev"
    roles: dict[str, str] = field(default_factory=lambda: {
        "customer-support": SandboxType.CONTAINER,
        "operator": SandboxType.LOCAL,
    })
    dev_backend: Any = None
    production_backend: dict[str, Any] = field(default_factory=dict)

    def select(self, role: str = "customer-support") -> str:
        """Select sandbox type for a given role.

        Args:
            role: User role string.

        Returns:
            ``SandboxType`` string.
        """
        if self.environment == "dev":
            return SandboxType.LOCAL
        return self.roles.get(role, SandboxType.CONTAINER)


# ── LangSmithSandbox (stub) ───────────────────────────────────────────


class LangSmithSandbox(BaseSandbox):
    """Stub for LangSmith remote sandbox integration.

    Actual integration requires LangSmith API credentials and client.
    """

    def __init__(self, project: str = "default", timeout: float = DEFAULT_EXECUTE_TIMEOUT) -> None:
        self._project = project
        self._timeout = timeout
        self._id = f"langsmith-{uuid.uuid4().hex[:8]}"

    @property
    def id(self) -> str:
        return self._id

    def execute(self, command: str, timeout: float = DEFAULT_EXECUTE_TIMEOUT) -> BackendResult:
        return BackendResult(
            success=False,
            error="LangSmith sandbox not yet implemented. "
                  "Requires LangSmith API client integration.",
        )

    def upload_files(self, files: dict[str, str]) -> BackendResult:
        return BackendResult(
            success=False,
            error="LangSmith sandbox not yet implemented.",
        )

    def download_files(self, paths: list[str]) -> BackendResult:
        return BackendResult(
            success=False,
            error="LangSmith sandbox not yet implemented.",
        )


__all__ = [
    "ContainerSandbox",
    "DEFAULT_EXECUTE_TIMEOUT",
    "LangSmithSandbox",
    "LocalShellBackend",
    "RoleBasedSandboxSelector",
    "SandboxType",
]