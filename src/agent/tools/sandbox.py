"""Sandboxed code-exec backends for the deep-agent backend.

This module implements the `SandboxBackendProtocol` in a *safe* way, standing
in contrast to deepagents' bundled **`LocalShellBackend`**:

- `LocalShellBackend` (`deepagents.backends.local_shell`) runs **arbitrary**
  shell commands on the host with **no isolation**. It is DEV ONLY and must
  never be used in production (see its own security warning, and
  docs/phase-0-discovery.md §4).
- `RestrictedShellSandbox` (defined here) subclasses `BaseSandbox` and runs a
  strict allowlist of **read-only** commands plus native, confined filesystem
  helpers (`ls`/`read`/`glob`/`grep`), denying every write operation.

!!! warning "Security model — read this before relying on it"

    `RestrictedShellSandbox` is a **best-effort host-level mitigation**, NOT a
    hard security boundary. Every check here is implemented in-process on the
    host; commands run under the current OS user, and a determined or unlucky
    caller can reach host files the sandbox cannot see. In particular:

    - Path confinement, flag allowlists, and the argv-only execution are
      intent-based guards against *accidental damage* and *accidental
      out-of-root reads*. They are not a defense against a malicious process.
    - "Read-only" means "the sandbox's own tooling refuses to mutate", not
      that the underlying OS forbids writes; any syscall the running user can
      perform is still possible (e.g. via `cat > /dev/whatever`).
    - A *real* production boundary requires a containerized
      `BaseSandbox` (Docker/VM) so that `execute()` runs in an isolated,
      non-privileged host. See `docs/phase-0-discovery.md` §4.

Because tool visibility is a *hard boundary* per role (plan §4.2), sandboxed
backends are only ever paired with roles whose tool set still includes
`execute`. See `src/agent/roles.py`.
"""

from __future__ import annotations

import asyncio
import os
import shlex
import subprocess
from dataclasses import dataclass

from deepagents.backends.protocol import (
    DeleteResult,
    EditResult,
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
    GlobResult,
    GrepResult,
    LsResult,
    ReadResult,
    WriteResult,
)
from deepagents.backends.sandbox import BaseSandbox

# Default subprocess timeout (seconds) when the caller does not pass one.
_DEFAULT_TIMEOUT_SECONDS: int = 30
"""Default `execute` timeout when the caller does not specify one (I3)."""


@dataclass(frozen=True)
class _CmdSpec:
    """Per-command allowlist describing which option tokens and args are safe."""

    # Whether positional args are filesystem paths that must be confinement-checked.
    takes_paths: bool
    # Single-dash option characters that are safe (no value).
    short_flags: frozenset[str] = frozenset()
    # Single-dash option characters that consume a value (e.g. `head -n 5`).
    short_values: frozenset[str] = frozenset()
    # Two-dash option names that are safe (no value, or a `--name=value` value).
    long_flags: frozenset[str] = frozenset()
    # Two-dash option names that consume a separate value argument.
    long_values: frozenset[str] = frozenset()


# A purely read-only core command set, each with explicit per-flag validation.
_COMMAND_SPECS: dict[str, _CmdSpec] = {
    # Operand-only commands: they print literals (or resolve command names),
    # never touch the filesystem.
    "pwd": _CmdSpec(takes_paths=False),
    "echo": _CmdSpec(takes_paths=False, short_flags=frozenset("neE")),
    "printf": _CmdSpec(takes_paths=False),
    "which": _CmdSpec(takes_paths=False, short_flags=frozenset("a")),
    # Path-taking, read-only listing/reading commands.
    "ls": _CmdSpec(
        takes_paths=True,
        short_flags=frozenset("aAlhRtrSF1din"),
        long_flags=frozenset(
            {"all", "almost-all", "recursive", "reverse", "size", "inode",
             "human-readable", "long", "directory", "color", "format",
             "sort", "time", "group-directories-first", "indicator-style"}
        ),
    ),
    "cat": _CmdSpec(
        takes_paths=True,
        short_flags=frozenset("nbsAveT"),
    ),
    "head": _CmdSpec(
        takes_paths=True,
        short_flags=frozenset("qv"),
        short_values=frozenset("nc"),
        long_flags=frozenset({"quiet", "verbose", "lines", "bytes"}),
    ),
    "tail": _CmdSpec(
        takes_paths=True,
        short_flags=frozenset("qv"),
        short_values=frozenset("nc"),
        long_flags=frozenset({"quiet", "verbose", "lines", "bytes"}),
    ),
    "wc": _CmdSpec(
        takes_paths=True,
        short_flags=frozenset("lwcmL"),
        long_flags=frozenset({"lines", "words", "bytes", "chars", "max-line-length"}),
    ),
    "grep": _CmdSpec(
        takes_paths=True,
        short_flags=frozenset("iRrnHlcoEFvwqxZsI"),
        short_values=frozenset("ABCe"),
        long_flags=frozenset(
            {"recursive", "dereference-recursive", "line-number", "count",
             "files-with-matches", "files-without-match", "only-matching",
             "extended-regexp", "fixed-strings", "invert-match", "quiet",
             "silent", "word-regexp", "line-regexp", "ignore-case",
             "with-filename", "no-filename", "null", "no-messages",
             "binary-files", "include", "exclude", "max-count", "color",
             "label", "context"}
        ),
    ),
    "sort": _CmdSpec(
        takes_paths=True,
        # Note: `-o`/`--output`/`--output-file` are deliberately ABSENT.
        short_flags=frozenset("nrufbchgMsz"),
        short_values=frozenset("tk"),
        long_flags=frozenset(
            {"numeric-sort", "reverse", "unique", "ignore-case",
             "ignore-leading-blanks", "check", "human-numeric-sort",
             "general-numeric-sort", "month-sort", "stable",
             "zero-terminated", "kind", "tie-break", "parallel"}
        ),
    ),
}

# A denylist of option strings that must never reach our allowlisted commands
# even though some lexical forms could otherwise slip through a flag check.
_NEVER_OPTIONS: tuple[str, ...] = (
    "-o",
    "--output",
    "--output-file",
    "--delete",
    "--exec",
    "--execdir",
    "--ok",
    "--write-out",
    "--fprint",
    "--fprint0",
    "--follow",
)


def _parse_command(command: str) -> list[str]:
    """Shell-split a command into tokens without executing it."""
    try:
        return shlex.split(command)
    except ValueError:
        return []


def _is_never_option(token: str) -> bool:
    return token in _NEVER_OPTIONS


def _validate_argv(program: str, tokens: list[str]) -> bool:
    """Validate the argv of an allowlisted `program`.

    Applies per-command flag rules and returns `True` only if every option is
    permitted (read-only) and the `--` terminator is handled.
    """
    spec = _COMMAND_SPECS[program]
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        if tok == "--":
            # Everything after `--` is a positional argument.
            return True
        if tok.startswith("--"):
            if _is_never_option(tok):
                return False
            name = tok.split("=", 1)[0]
            if name in spec.long_flags:
                i += 1
                continue
            if name in spec.long_values:
                # Consumes the next token as its value.
                i += 2
                continue
            return False
        if tok.startswith("-") and tok != "-":
            chars = tok[1:]
            # A value-taking short option consumes the NEXT token only when it
            # is the LAST char of the option cluster (split form `-n 5`). When
            # the value is attached (`-n5`, `-k1`, `-eroot`), the attached
            # remainder is the value; the following token is a real operand
            # that must still be confinement-checked.
            value_taken = False
            j = 0
            while j < len(chars):
                ch = chars[j]
                if ch in spec.short_values:
                    value_taken = j == len(chars) - 1
                    break
                if ch not in spec.short_flags:
                    return False
                j += 1
            i += 2 if value_taken else 1
            continue
        # Positional argument.
        i += 1
    return True


_SHELL_METACHARS: str = ";|&$`<>()\n\t"
"""Characters that are suspicious in an operand of a no-path command.

Used only for `echo`/`printf`-style operands, where such sequences achieve
nothing useful in a read-only context but indicate a command-injection attempt
(e.g. `echo $(id)`). No shell is ever spawned — argv is executed directly — so
these are inert; this check is defense-in-depth against confusing the model,
not a security boundary.
"""


def _is_allowed(command: str) -> list[str] | None:
    """Return the validated argv of `command`, or `None` if it is not permitted."""
    tokens = _parse_command(command)
    if not tokens:
        return None

    program = tokens[0]
    if program not in _COMMAND_SPECS:
        return None

    # Validate options first (so a rejected token fails before path checks).
    if not _validate_argv(program, tokens[1:]):
        return None

    # Path/output confinement for path-taking commands happens in `execute`,
    # which knows the working directory; operands of no-path commands are
    # checked for shell metacharacters there too (defense-in-depth).
    return tokens


class RestrictedShellSandbox(BaseSandbox):
    """A `BaseSandbox` that only runs read-only, path-confined commands.

    Provide the full `BackendProtocol` (ls/read/glob/grep) via **native**
    (pathlib/os) implementations — never by routing shell `python3 -c` scripts
    through `execute()` — so a model can actually list, read, and search the
    sandbox. `execute()` itself is deliberately crippled to read-only, in-root
    commands, and every write operation (`write_file`/`edit_file`/`delete`/
    upload) is denied.

    !!! warning

        This is a **best-effort host-level mitigation**, NOT a security
        boundary (see the module docstring). Do not treat path confinement or
        the read-only allowlist as a guarantee against a malicious or
        determined process; production isolation requires a containerized
        `BaseSandbox`.

    Args:
        root_dir: Base directory for the sandbox's configurable view. Defaults
            to the current working directory.
        containment_root: Root directory to which `execute` path arguments and
            native helper reads are confined. Defaults to `root_dir`. Exposed
            so a caller can confine reads to a narrower sub-tree.
        default_timeout: Subprocess timeout (seconds) applied to every
            `execute` when the caller does not pass one. Defaults to 30s.
    """

    def __init__(
        self,
        root_dir: str | os.PathLike | None = None,
        *,
        containment_root: str | os.PathLike | None = None,
        default_timeout: int | None = None,
    ) -> None:
        self._root = str(root_dir) if root_dir is not None else os.getcwd()
        self._root_real = os.path.realpath(self._root)
        # Cached default timeout for `execute` (I3): the abstract protocol says
        # `timeout=None` means "backend default"; we satisfy that by supplying
        # our own.
        self._default_timeout = (
            _DEFAULT_TIMEOUT_SECONDS if default_timeout is None else int(default_timeout)
        )
        self._containment = (
            os.path.realpath(containment_root) if containment_root is not None else self._root_real
        )
        super().__init__()

    @property
    def id(self) -> str:
        """A stable identifier for this sandbox instance."""
        return f"restricted-shell-{os.getpid()}"

    # ------------------------------------------------------------------ #
    # Path-confinement helpers                                            #
    # ------------------------------------------------------------------ #
    def _resolve(self, path: str, *, cwd: str | None = None) -> str:
        """Return the absolute realpath of `path`, resolving relative to `cwd`."""
        base = cwd if cwd is not None else self._containment
        if not os.path.isabs(path):
            path = os.path.join(base, path)
        return os.path.realpath(path)

    def _confined(self, real: str) -> bool:
        """Return True if absolute realpath `real` is inside the containment root."""
        if real == self._containment:
            return True
        return real.startswith(self._containment + os.sep)

    def _confine(self, path: str, *, cwd: str | None = None) -> str:
        """Resolve and confinement-check `path`; raise `PermissionError` if escaped."""
        real = self._resolve(path, cwd=cwd)
        if not self._confined(real):
            raise PermissionError(f"path escapes sandbox root: {path!r}")
        return real

    # ------------------------------------------------------------------ #
    # execute: argv-only, per-command validated, path-confined             #
    # ------------------------------------------------------------------ #
    def execute(
        self,
        command: str,
        *,
        timeout: int | None = None,
    ) -> ExecuteResponse:
        """Run `command` read-only, argv-only, and confined to the sandbox root.

        The command string is parsed (never handed to a shell), its program
        word must be allowlisted, its flags validated per-command, and every
        file-ish argument resolved and checked against the containment root
        before execution. `timeout=None` uses the backend's configured
        `default_timeout`.
        """
        tokens = _is_allowed(command)
        if tokens is None:
            return ExecuteResponse(
                output=f"Error: command rejected by sandbox allowlist: {command!r}",
                exit_code=1,
                truncated=False,
            )

        program = tokens[0]
        spec = _COMMAND_SPECS[program]
        cwd = self._root_real

        if spec.takes_paths:
            # Separate value-options (so we do not misclassify a value as a path).
            operands = _collect_operands(program, tokens[1:])
            try:
                for operand in operands:
                    self._confine(operand, cwd=cwd)
            except PermissionError as exc:
                return ExecuteResponse(
                    output=f"Error: command rejected: {exc}",
                    exit_code=1,
                    truncated=False,
                )
        else:
            # No paths; reject shell-metachar operands up front.
            for tok in tokens[1:]:
                if tok == "--":
                    break
                if tok.startswith("-") and tok != "-":
                    continue
                if any(ch in _SHELL_METACHARS for ch in tok):
                    return ExecuteResponse(
                        output=f"Error: command rejected: shell metacharacter in operand {tok!r}",
                        exit_code=1,
                        truncated=False,
                    )

        effective_timeout = self._default_timeout if timeout is None else timeout
        try:
            result = subprocess.run(  # noqa: S603  # argv-only, allowlisted, validated
                tokens,
                check=False,
                shell=False,
                capture_output=True,
                stdin=subprocess.DEVNULL,
                text=True,
                timeout=effective_timeout,
                cwd=cwd,
            )
        except subprocess.TimeoutExpired:
            return ExecuteResponse(
                output=f"Error: command timed out after {effective_timeout}s.",
                exit_code=124,
                truncated=False,
            )
        except OSError as exc:
            return ExecuteResponse(
                output=f"Error: could not execute {program!r}: {exc}",
                exit_code=127,
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

    # ------------------------------------------------------------------ #
    # Native (non-shell) read-only filesystem helpers (I2)                #
    # ------------------------------------------------------------------ #
    def ls(self, path: str) -> LsResult:
        """List a directory confined to the containment root."""
        try:
            scanned = self._confine(path)
        except PermissionError as exc:
            return LsResult(entries=None, error=f"Path '{path}': {exc}")
        if not os.path.isdir(scanned):
            return LsResult(entries=None, error=f"Path '{path}': not_a_directory")
        entries: list = []
        try:
            with os.scandir(scanned) as it:
                for entry in it:
                    entries.append(
                        {
                            "path": os.path.join(scanned, entry.name),
                            "is_dir": entry.is_dir(follow_symlinks=False),
                        }
                    )
        except PermissionError:
            return LsResult(entries=None, error=f"Path '{path}': permission_denied")
        except OSError:
            return LsResult(entries=None, error=f"Path '{path}': unreadable")
        return LsResult(entries=entries)

    async def als(self, path: str) -> LsResult:
        return await asyncio.to_thread(self.ls, path)

    def read(
        self,
        file_path: str,
        offset: int = 0,
        limit: int = 2000,
    ) -> ReadResult:
        """Read a text file within the containment root (read-only)."""
        try:
            full = self._confine(file_path)
        except PermissionError as exc:
            return ReadResult(error=f"File '{file_path}': {exc}")
        if not os.path.isfile(full):
            return ReadResult(error=f"File '{file_path}': file_not_found")
        try:
            with open(full, "r", encoding="utf-8", errors="surrogateescape") as fh:
                lines = fh.readlines()
        except PermissionError:
            return ReadResult(error=f"File '{file_path}': permission_denied")
        except OSError as exc:
            return ReadResult(error=f"File '{file_path}': {exc}")

        start = max(offset, 0)
        if start > len(lines):
            return ReadResult(error=f"File '{file_path}': offset exceeds file length")

        if limit is not None and limit <= 0:
            # Explicit zero/negative window: report an uninspected window.
            return ReadResult(file_data={"content": "", "encoding": "utf-8"}, no_lines_requested=True)

        end = len(lines)
        if limit is not None and limit > 0:
            end = min(len(lines), start + limit)

        page = lines[start:end]
        content = "".join(page)

        # Empty page (empty file or offset at EOF): no window to report, so all
        # pagination fields stay unset to keep `ReadResult.__post_init__` valid.
        if not page:
            return ReadResult(file_data={"content": content, "encoding": "utf-8"})

        total = len(lines)
        return ReadResult(
            file_data={"content": content, "encoding": "utf-8"},
            total_lines=total,
            start_line=start + 1,
            end_line=end,
            next_offset=end if end < total else None,
        )

    async def aread(
        self,
        file_path: str,
        offset: int = 0,
        limit: int = 2000,
    ) -> ReadResult:
        return await asyncio.to_thread(self.read, file_path, offset, limit)

    def glob(self, pattern: str, path: str | None = None) -> GlobResult:
        """Glob-match regular files under a confined root (read-only)."""
        root = path if path is not None else self._containment
        try:
            root_real = self._confine(root)
        except PermissionError as exc:
            return GlobResult(matches=None, error=f"Path '{root}': {exc}")
        if not os.path.isdir(root_real):
            return GlobResult(matches=None, error=f"Path '{root}': not_a_directory")

        import fnmatch

        matches: list = []
        for dirpath, dirnames, filenames in os.walk(root_real):
            for name in filenames:
                full = os.path.join(dirpath, name)
                real = os.path.realpath(full)
                if not self._confined(real):
                    continue
                rel = os.path.relpath(full, root_real)
                if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(name, pattern):
                    matches.append({"path": real, "is_dir": False})
        return GlobResult(matches=matches)

    async def aglob(self, pattern: str, path: str | None = None) -> GlobResult:
        return await asyncio.to_thread(self.glob, pattern, path)

    def grep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
        *,
        max_count: int | None = None,
    ) -> GrepResult:
        """Search file contents for a literal string within the containment root."""
        root = path if path is not None else self._containment
        try:
            root_real = self._confine(root)
        except PermissionError as exc:
            return GrepResult(error=f"Path '{root}': {exc}")

        import fnmatch

        targets: list[str] = []
        if os.path.isdir(root_real):
            for dirpath, _dirnames, filenames in os.walk(root_real):
                for name in filenames:
                    full = os.path.join(dirpath, name)
                    real = os.path.realpath(full)
                    if not self._confined(real):
                        continue
                    if glob and not (
                        fnmatch.fnmatch(name, glob)
                        or fnmatch.fnmatch(os.path.relpath(real, root_real), glob)
                    ):
                        continue
                    targets.append(real)
        elif os.path.isfile(root_real):
            targets = [root_real]
        else:
            return GrepResult(error=f"Path '{root}': path_not_found")

        matches: list = []
        truncated = False
        for target in targets:
            try:
                with open(target, "r", encoding="utf-8", errors="ignore") as fh:
                    for i, line in enumerate(fh, 1):
                        if pattern in line:
                            matches.append(
                                {"path": target, "line": i, "text": line.rstrip("\r\n")}
                            )
                            if max_count is not None and len(matches) >= max_count:
                                truncated = True
                                break
            except OSError:
                continue
            if truncated:
                break
        if truncated:
            return GrepResult(matches=matches, truncated=True)
        return GrepResult(matches=matches)

    async def agrep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
        *,
        max_count: int | None = None,
    ) -> GrepResult:
        return await asyncio.to_thread(self.grep, pattern, path, glob, max_count=max_count)

    # ------------------------------------------------------------------ #
    # Write/delete operations: denied (read-only sandbox)                 #
    # ------------------------------------------------------------------ #
    def write(self, file_path: str, content: str) -> WriteResult:
        return WriteResult(error=f"Failed to write file '{file_path}': read_only_sandbox")

    async def awrite(self, file_path: str, content: str) -> WriteResult:
        return await asyncio.to_thread(self.write, file_path, content)

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,  # noqa: FBT001,FBT002
    ) -> EditResult:
        return EditResult(error=f"read_only_sandbox: edit '{file_path}' denied")

    async def aedit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,  # noqa: FBT001,FBT002
    ) -> EditResult:
        return await asyncio.to_thread(
            self.edit, file_path, old_string, new_string, replace_all
        )

    def delete(self, file_path: str) -> DeleteResult:
        return DeleteResult(error=f"read_only_sandbox: delete '{file_path}' denied")

    # ------------------------------------------------------------------ #
    # Upload/download                                                     #
    # ------------------------------------------------------------------ #
    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """No-op uploads are unsupported: this sandbox is read-only."""
        return [FileUploadResponse(path=path, error="read_only_sandbox") for path, _ in files]

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Open and return files that exist inside the containment root."""
        responses: list[FileDownloadResponse] = []
        for path in paths:
            try:
                full = self._confine(path)
            except PermissionError:
                responses.append(FileDownloadResponse(path=path, error="permission_denied"))
                continue
            try:
                with open(full, "rb") as fh:
                    responses.append(FileDownloadResponse(path=path, content=fh.read()))
            except (FileNotFoundError, IsADirectoryError, PermissionError, OSError) as exc:
                responses.append(FileDownloadResponse(path=path, error=str(exc)))
        return responses


def _collect_operands(program: str, tokens: list[str]) -> list[str]:
    """Return the positional (non-option) args of a validated command argv.

    Skips option tokens and the values consumed by value-taking options so
    that only true file operands are confinement-checked.
    """
    spec = _COMMAND_SPECS[program]
    operands: list[str] = []
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        if tok == "--":
            operands.extend(tokens[i + 1 :])
            break
        if tok.startswith("--"):
            name = tok.split("=", 1)[0]
            if name in spec.long_values:
                i += 2
            else:
                i += 1
            continue
        if tok.startswith("-") and tok != "-":
            chars = tok[1:]
            # Consume the next token as a value only for the split form, where
            # the value-taking short option is the LAST char of the cluster
            # (`-n 5`). If the value is attached (`-n5`/`-k1`/`-eroot`), the
            # attached remainder is the value and the following token is a file
            # operand that must NOT be skipped.
            value_taken = False
            j = 0
            while j < len(chars):
                ch = chars[j]
                if ch in spec.short_values:
                    value_taken = j == len(chars) - 1
                    break
                if ch not in spec.short_flags:
                    break
                j += 1
            i += 2 if value_taken else 1
            continue
        operands.append(tok)
        i += 1
    return operands


__all__ = [
    "RestrictedShellSandbox",
]
