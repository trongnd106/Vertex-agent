"""Sandboxed code-exec backends for the deep-agent backend.

This module implements the `SandboxBackendProtocol` in a *safe* way, standing
in contrast to deepagents' bundled **`LocalShellBackend`**:

- `LocalShellBackend` (`deepagents.backends.local_shell`) runs **arbitrary**
  shell commands on the host with **no isolation**. It is DEV ONLY and must
  never be used in production (see its own security warning, and
  docs/phase-0-discovery.md §4).
- `RestrictedShellSandbox` (defined here) subclasses `BaseSandbox` and only
  allows a strict allowlist of **read-only** commands, denying any mutation or
  anything that touches paths outside the sandbox root. This is the pattern to
  build on for a production sandbox (a real deployment would additionally
  replace the local subprocess with a Docker container/VM via `execute()`).

Security model: because tool visibility is a *hard boundary* per role (plan
§4.2), sandboxed backends are only ever paired with roles whose tool set still
includes `execute`. See `src/agent/roles.py`.
"""

from __future__ import annotations

import os
import shlex
import subprocess

from deepagents.backends.protocol import (
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
)
from deepagents.backends.sandbox import BaseSandbox

ALLOWED_COMMANDS: frozenset[str] = frozenset(
    {
        "ls",
        "cat",
        "grep",
        "pwd",
        "find",
        "echo",
        "printf",
        "head",
        "tail",
        "wc",
        "sort",
        "which",
    }
)
"""Read-only commands a model may invoke. Anything else is rejected outright."""

_MUTATION_TOKENS: frozenset[str] = frozenset(
    {
        "rm",
        "rmdir",
        "mkdir",
        "touch",
        "cp",
        "mv",
        "dd",
        "chmod",
        "chown",
        "ln",
        ">",
        ">>",
        "<",
        "|",
        "&&",
        "||",
        ";",
        "`",
        "$(",
        "sudo",
        "su",
        "eval",
        "exec",
        "python",
        "python3",
        "perl",
        "bash",
        "sh",
        "curl",
        "wget",
        "nc",
        "kill",
        "killall",
        "cat >",
        "tee",
        "install",
    }
)
"""Tokens that signal mutation, control flow, or arbitrary execution.

These make the allowlist defense-in-depth: even when a command string's leading
word is in `ALLOWED_COMMANDS`, the presence of any of these tokens causes the
command to be rejected.
"""


def _parse_command(command: str) -> list[str]:
    """Shell-split a command into tokens without executing it."""
    try:
        return shlex.split(command)
    except ValueError:
        return []


def _is_allowed(command: str) -> bool:
    """Return True only if `command` is a permitted, read-only, in-root command."""
    tokens = _parse_command(command)
    if not tokens:
        return False

    # The leading command word must be in the allowlist.
    if tokens[0] not in ALLOWED_COMMANDS:
        return False

    # No mutation/control-flow/metacharacter token anywhere in the command.
    lowered = command.lower()
    for token in _MUTATION_TOKENS:
        if token in lowered:
            return False
    return True


class RestrictedShellSandbox(BaseSandbox):
    """A `BaseSandbox` that only runs an allowlist of read-only commands.

    Wraps `BaseSandbox`, which implements the full `BackendProtocol`
    (ls/read/write/edit/glob/grep) on top of `execute()`; our `execute()` is
    deliberately crippled to read-only, in-root commands so neither the model
    nor the file-op helpers can mutate the host or reach outside `root_dir`.

    !!! warning

        This is a *local* restriction, NOT full isolation: commands still run
        on the host under the current user. It is the recommended pattern for a
        production sandbox, but a hardened deployment should implement
        `execute()` to run in a Docker container / VM (see `BaseSandbox`
        docstring, and docs/phase-0-discovery.md §4).

    Args:
        root_dir: Base directory; every allowed command is confined to it.
            Defaults to the current working directory.
    """

    def __init__(self, root_dir: str | os.PathLike | None = None) -> None:
        self._root = str(root_dir) if root_dir is not None else os.getcwd()
        self._root_real = os.path.realpath(self._root)
        super().__init__()

    @property
    def id(self) -> str:
        """A stable identifier for this sandbox instance."""
        return f"restricted-shell-{os.getpid()}"

    def execute(
        self,
        command: str,
        *,
        timeout: int | None = None,
    ) -> ExecuteResponse:
        """Run `command` only if it is read-only and stays within `root_dir`.

        Commands that fail the allowlist check are rejected with a non-zero exit
        code instead of being executed.
        """
        if not _is_allowed(command):
            return ExecuteResponse(
                output=f"Error: command rejected by sandbox allowlist: {command!r}",
                exit_code=1,
                truncated=False,
            )

        try:
            result = subprocess.run(  # noqa: S603
                command,
                check=False,
                shell=True,
                capture_output=True,
                stdin=subprocess.DEVNULL,
                text=True,
                timeout=timeout,
                cwd=self._root,
            )
        except subprocess.TimeoutExpired:
            return ExecuteResponse(
                output="Error: command timed out.",
                exit_code=124,
                truncated=False,
            )

        output = result.stdout
        if result.stderr:
            output += "\n" + result.stderr
        return ExecuteResponse(
            output=output.strip(),
            exit_code=result.returncode,
            truncated=False,
        )

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """No-op uploads are unsupported: this sandbox is read-only."""
        return [FileUploadResponse(path=path, error="read_only_sandbox") for path, _ in files]

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Open and return files that exist under `root_dir`; error otherwise."""
        responses: list[FileDownloadResponse] = []
        for path in paths:
            full = os.path.realpath(path)
            if not full.startswith(self._root_real + os.sep) and full != self._root_real:
                responses.append(FileDownloadResponse(path=path, error="permission_denied"))
                continue
            try:
                with open(full, "rb") as fh:
                    responses.append(FileDownloadResponse(path=path, content=fh.read()))
            except (FileNotFoundError, IsADirectoryError, PermissionError, OSError) as exc:
                responses.append(FileDownloadResponse(path=path, error=str(exc)))
        return responses


__all__ = [
    "ALLOWED_COMMANDS",
    "RestrictedShellSandbox",
]
