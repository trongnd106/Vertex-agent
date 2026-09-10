"""Backend implementations: StateBackend, FilesystemBackend, CompositeBackend.

Provides:
- ``StateBackend`` — in-memory, checkpointed, non-persistent across threads
- ``FilesystemBackend`` — disk operations with root directory isolation
- ``CompositeBackend`` — route-based multiplexing with default + routes
"""

from __future__ import annotations

import fnmatch
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

from src.backends.protocol import BackendProtocol, BackendResult, FileInfo


# ── StateBackend ──────────────────────────────────────────────────────


class StateBackend(BackendProtocol):
    """In-memory, checkpointed backend. Not persistent across threads.

    Stores all files in a dict. Useful for testing and transient state.

    All paths are normalized: leading ``/`` is stripped internally so that
    ``/foo/bar.txt`` and ``foo/bar.txt`` refer to the same entry.
    """

    def __init__(self) -> None:
        self._files: dict[str, str] = {}
        self._checkpoint: dict[str, str] = {}

    @staticmethod
    def _norm(path: str) -> str:
        return path.lstrip("/")

    def ls(self, path: str = "") -> BackendResult:
        path = self._norm(path)
        prefix = path + "/" if path else ""
        entries: set[str] = set()

        if path and path in self._files:
            name = path.rsplit("/", 1)[-1] if "/" in path else path
            entries.add(name)

        for key in self._files:
            if prefix and not key.startswith(prefix):
                continue
            remainder = key[len(prefix):] if prefix else key
            if "/" in remainder:
                dir_name = remainder.split("/", 1)[0]
                entries.add(dir_name)
            else:
                entries.add(remainder)

        file_infos = []
        for name in sorted(entries):
            full = prefix + name
            is_dir = full not in self._files
            file_infos.append(
                FileInfo(
                    name=name,
                    path=full,
                    size=len(self._files.get(full, "")) if not is_dir else 0,
                    modified=time.time(),
                    is_dir=is_dir,
                    permissions="rw-rw-r--",
                )
            )
        return BackendResult(data=file_infos)

    def read(self, path: str) -> BackendResult:
        path = self._norm(path)
        if path not in self._files:
            return BackendResult(success=False, error=f"File not found: {path}")
        return BackendResult(data=self._files[path])

    def write(self, path: str, content: str) -> BackendResult:
        self._files[self._norm(path)] = content
        return BackendResult(data=None)

    def edit(self, path: str, old: str, new: str) -> BackendResult:
        path = self._norm(path)
        if path not in self._files:
            return BackendResult(success=False, error=f"File not found: {path}")
        if old not in self._files[path]:
            return BackendResult(
                success=False, error=f"String not found in {path}"
            )
        self._files[path] = self._files[path].replace(old, new, 1)
        return BackendResult(data=None)

    def delete(self, path: str) -> BackendResult:
        path = self._norm(path)
        if path in self._files:
            del self._files[path]
            return BackendResult(data=None)
        keys_to_delete = [k for k in self._files if k.startswith(path + "/")]
        if not keys_to_delete:
            return BackendResult(success=False, error=f"Not found: {path}")
        for k in keys_to_delete:
            del self._files[k]
        return BackendResult(data=None)

    def glob(self, pattern: str) -> BackendResult:
        matches = [k for k in self._files if fnmatch.fnmatch(k, pattern)]
        return BackendResult(data=sorted(matches))

    def grep(self, pattern: str, path: str = "") -> BackendResult:
        results: list[dict[str, Any]] = []
        compiled = re.compile(pattern)
        path = self._norm(path)
        prefix = path + "/" if path else ""
        for key in self._files:
            if path and not key.startswith(prefix):
                continue
            for i, line in enumerate(self._files[key].splitlines(), 1):
                if compiled.search(line):
                    results.append({"file": key, "line": i, "content": line})
        return BackendResult(data=results)

    def download_files(self, paths: list[str]) -> BackendResult:
        contents: dict[str, str] = {}
        for p in paths:
            if p in self._files:
                contents[p] = self._files[p]
        return BackendResult(data=contents)

    def upload_files(self, files: dict[str, str]) -> BackendResult:
        self._files.update(files)
        return BackendResult(data=None)

    # ── Checkpoint helpers ────────────────────────────────────────────

    def checkpoint(self) -> None:
        """Save a snapshot of current state for rollback."""
        self._checkpoint = dict(self._files)

    def rollback(self) -> None:
        """Restore state to the last checkpoint."""
        self._files = dict(self._checkpoint)


# ── FilesystemBackend ─────────────────────────────────────────────────


class FilesystemBackend(BackendProtocol):
    """Disk-backed backend with root directory isolation.

    All operations are scoped to ``root_dir``. Path traversal outside
    the root is blocked.
    """

    def __init__(self, root_dir: str) -> None:
        self._root = os.path.abspath(root_dir)
        os.makedirs(self._root, exist_ok=True)

    def _resolve(self, path: str) -> str:
        """Resolve a relative path to an absolute path inside root."""
        full = os.path.normpath(os.path.join(self._root, path))
        if not full.startswith(self._root):
            raise PermissionError(f"Path traversal blocked: {path}")
        return full

    def ls(self, path: str = "") -> BackendResult:
        try:
            target = self._resolve(path)
            entries: list[FileInfo] = []
            for name in sorted(os.listdir(target)):
                full = os.path.join(target, name)
                rel = os.path.relpath(full, self._root)
                st = os.stat(full)
                entries.append(
                    FileInfo(
                        name=name,
                        path=rel,
                        size=st.st_size,
                        modified=st.st_mtime,
                        is_dir=os.path.isdir(full),
                        permissions=self._perm_string(st.st_mode),
                    )
                )
            return BackendResult(data=entries)
        except FileNotFoundError as exc:
            return BackendResult(success=False, error=str(exc))
        except PermissionError as exc:
            return BackendResult(success=False, error=str(exc))

    def read(self, path: str) -> BackendResult:
        try:
            full = self._resolve(path)
            with open(full, "r") as f:
                return BackendResult(data=f.read())
        except (FileNotFoundError, IsADirectoryError, OSError) as exc:
            return BackendResult(success=False, error=str(exc))

    def write(self, path: str, content: str) -> BackendResult:
        try:
            full = self._resolve(path)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w") as f:
                f.write(content)
            return BackendResult(data=None)
        except (OSError, PermissionError) as exc:
            return BackendResult(success=False, error=str(exc))

    def edit(self, path: str, old: str, new: str) -> BackendResult:
        try:
            full = self._resolve(path)
            with open(full, "r") as f:
                content = f.read()
            if old not in content:
                return BackendResult(
                    success=False, error=f"String not found in {path}"
                )
            content = content.replace(old, new, 1)
            with open(full, "w") as f:
                f.write(content)
            return BackendResult(data=None)
        except (FileNotFoundError, OSError) as exc:
            return BackendResult(success=False, error=str(exc))

    def delete(self, path: str) -> BackendResult:
        try:
            full = self._resolve(path)
            if os.path.isdir(full):
                import shutil
                shutil.rmtree(full)
            else:
                os.remove(full)
            return BackendResult(data=None)
        except (FileNotFoundError, OSError) as exc:
            return BackendResult(success=False, error=str(exc))

    def glob(self, pattern: str) -> BackendResult:
        try:
            import glob as glob_mod
            full_pattern = os.path.join(self._root, pattern)
            matches = [
                os.path.relpath(p, self._root)
                for p in glob_mod.glob(full_pattern, recursive=True)
            ]
            return BackendResult(data=sorted(matches))
        except PermissionError as exc:
            return BackendResult(success=False, error=str(exc))

    def grep(self, pattern: str, path: str = "") -> BackendResult:
        results: list[dict[str, Any]] = []
        compiled = re.compile(pattern)
        search_root = self._resolve(path) if path else self._root
        try:
            for dirpath, _, filenames in os.walk(search_root):
                for fname in filenames:
                    full = os.path.join(dirpath, fname)
                    try:
                        with open(full, "r", errors="ignore") as f:
                            for i, line in enumerate(f, 1):
                                if compiled.search(line.rstrip()):
                                    rel = os.path.relpath(full, self._root)
                                    results.append({
                                        "file": rel,
                                        "line": i,
                                        "content": line.rstrip(),
                                    })
                    except (OSError, UnicodeDecodeError):
                        continue
            return BackendResult(data=results)
        except PermissionError as exc:
            return BackendResult(success=False, error=str(exc))

    def download_files(self, paths: list[str]) -> BackendResult:
        contents: dict[str, str] = {}
        for p in paths:
            result = self.read(p)
            if result.success:
                contents[p] = result.data
        return BackendResult(data=contents)

    def upload_files(self, files: dict[str, str]) -> BackendResult:
        for path, content in files.items():
            result = self.write(path, content)
            if not result.success:
                return result
        return BackendResult(data=None)

    @staticmethod
    def _perm_string(mode: int) -> str:
        """Convert a stat mode to a permission string (e.g. rw-r--r--)."""
        perms = ""
        for who in "USR", "GRP", "OTH":
            for what in "R", "W", "X":
                if mode & getattr(__import__("stat"), f"S_I{what}{who}"):
                    perms += what.lower()
                else:
                    perms += "-"
        return perms


# ── CompositeBackend ──────────────────────────────────────────────────


class CompositeBackend(BackendProtocol):
    """Route-based multiplexing over multiple backends.

    Routes are evaluated as fnmatch patterns against the requested path.
    The first matching route's backend is used. Falls back to ``default``.
    """

    def __init__(
        self,
        default: BackendProtocol,
        routes: dict[str, BackendProtocol] | None = None,
    ) -> None:
        self._default = default
        self._routes = dict(routes or {})

    def add_route(self, pattern: str, backend: BackendProtocol) -> None:
        """Add a route pattern → backend mapping.

        Args:
            pattern: fnmatch pattern (e.g. ``"logs/*"``).
            backend: Backend to route matching paths to.
        """
        self._routes[pattern] = backend

    def remove_route(self, pattern: str) -> bool:
        """Remove a route by pattern.

        Returns:
            True if removed.
        """
        if pattern in self._routes:
            del self._routes[pattern]
            return True
        return False

    def _select(self, path: str) -> BackendProtocol:
        for pattern, backend in self._routes.items():
            if fnmatch.fnmatch(path, pattern):
                return backend
        return self._default

    def ls(self, path: str = "") -> BackendResult:
        return self._select(path).ls(path)

    def read(self, path: str) -> BackendResult:
        return self._select(path).read(path)

    def write(self, path: str, content: str) -> BackendResult:
        return self._select(path).write(path, content)

    def edit(self, path: str, old: str, new: str) -> BackendResult:
        return self._select(path).edit(path, old, new)

    def delete(self, path: str) -> BackendResult:
        return self._select(path).delete(path)

    def glob(self, pattern: str) -> BackendResult:
        return self._select(pattern).glob(pattern)

    def grep(self, pattern: str, path: str = "") -> BackendResult:
        return self._select(path).grep(pattern, path)

    def download_files(self, paths: list[str]) -> BackendResult:
        by_backend: dict[str, tuple[BackendProtocol, list[str]]] = {}
        for p in paths:
            backend = self._select(p)
            by_backend.setdefault(backend, []).append(p)
        contents: dict[str, str] = {}
        for backend, p_list in by_backend.items():
            result = backend.download_files(p_list)
            if result.success and isinstance(result.data, dict):
                contents.update(result.data)
        return BackendResult(data=contents)

    def upload_files(self, files: dict[str, str]) -> BackendResult:
        by_backend: dict[BackendProtocol, dict[str, str]] = {}
        for path, content in files.items():
            backend = self._select(path)
            by_backend.setdefault(backend, {})[path] = content
        for backend, fdict in by_backend.items():
            result = backend.upload_files(fdict)
            if not result.success:
                return result
        return BackendResult(data=None)


__all__ = [
    "CompositeBackend",
    "FilesystemBackend",
    "StateBackend",
]