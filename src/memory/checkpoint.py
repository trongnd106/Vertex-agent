"""Checkpoint system for session-level short-term memory.

Provides checkpoint/restore of graph state after each execution step,
enabling time travel, crash recovery, and session persistence.

Inspired by LangGraph's ``BaseCheckpointSaver`` with support for
``PendingWrite``, checkpoint metadata, and multiple backends.
"""

from __future__ import annotations

import copy
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

from src.graph.types import END


# ── Checkpoint data types ───────────────────────────────────────────────


@dataclass
class PendingWrite:
    """A pending write to a channel that hasn't been committed yet.

    Used for crash recovery — if the process crashes after a write
    is recorded but before it's applied, the pending write can be
    replayed.
    """

    channel: str
    value: Any
    task_id: str = ""


@dataclass
class Checkpoint:
    """Snapshot of graph state at a point in time.

    Schema mirrors LangGraph's ``Checkpoint``:
    - ``v``: version (currently 1)
    - ``id``: unique checkpoint ID (usually a UUID string)
    - ``ts``: timestamp (seconds since epoch)
    - ``channel_values``: current values of all state channels
    - ``channel_versions``: version counter per channel (monotonic)
    - ``versions_seen``: per-node tracking of which channel versions
      each node has seen (for node-level scheduling)
    - ``pending_sends``: pending ``Send`` operations not yet dispatched
    """

    v: int = 1
    id: str = ""
    ts: float = 0.0
    channel_values: dict[str, Any] = field(default_factory=dict)
    channel_versions: dict[str, int] = field(default_factory=dict)
    versions_seen: dict[str, dict[str, int]] = field(default_factory=dict)
    pending_sends: list[Any] = field(default_factory=list)

    def copy(self) -> Checkpoint:
        """Create a deep copy of this checkpoint."""
        return Checkpoint(
            v=self.v,
            id=self.id,
            ts=self.ts,
            channel_values=copy.deepcopy(self.channel_values),
            channel_versions=copy.copy(self.channel_versions),
            versions_seen=copy.deepcopy(self.versions_seen),
            pending_sends=copy.deepcopy(self.pending_sends),
        )


@dataclass
class CheckpointMetadata:
    """Metadata associated with a checkpoint.

    - ``source``: origin (``'step'``, ``'input'``, ``'loop'``, ``'update'``)
    - ``step``: step number when checkpoint was taken
    - ``parents``: parent checkpoint IDs (for branching/time-travel)
    - ``run_id``: the run this checkpoint belongs to
    - ``thread_id``: the thread/conversation this checkpoint belongs to
    """

    source: str = "step"
    step: int = 0
    parents: dict[str, str] = field(default_factory=dict)
    run_id: str = ""
    thread_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "step": self.step,
            "parents": self.parents,
            "run_id": self.run_id,
            "thread_id": self.thread_id,
        }


# ── Base checkpoint saver ───────────────────────────────────────────────


class BaseCheckpointSaver(ABC):
    """Abstract base for checkpoint persistence backends.

    Methods:
        get: Retrieve a single checkpoint by ID.
        get_tuple: Retrieve checkpoint with its pending writes.
        list: List checkpoint IDs matching a filter, newest-first.
        put: Store a new checkpoint.
        put_writes: Store pending writes for crash recovery.
    """

    @abstractmethod
    def get(self, config: dict[str, Any]) -> Checkpoint | None:
        """Get the checkpoint for a given config.

        Args:
            config: Dict containing at least ``configurable`` key
                    with ``thread_id`` and optionally ``checkpoint_id``.

        Returns:
            The checkpoint or None.
        """
        ...

    @abstractmethod
    def get_tuple(
        self, config: dict[str, Any]
    ) -> tuple[Checkpoint, list[PendingWrite]] | None:
        """Get checkpoint and its pending writes.

        Returns:
            ``(checkpoint, pending_writes)`` or None.
        """
        ...

    @abstractmethod
    def list(
        self,
        config: dict[str, Any],
        *,
        before: Checkpoint | None = None,
        limit: int = 10,
    ) -> list[Checkpoint]:
        """List checkpoints for a thread, newest-first.

        Args:
            config: Dict with ``configurable.thread_id``.
            before: If given, only return checkpoints before this one.
            limit: Max checkpoints to return.

        Returns:
            List of checkpoints.
        """
        ...

    @abstractmethod
    def put(
        self,
        config: dict[str, Any],
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
    ) -> None:
        """Store a checkpoint.

        Args:
            config: Dict with ``configurable.thread_id``.
            checkpoint: The checkpoint to store.
            metadata: Associated metadata.
        """
        ...

    @abstractmethod
    def put_writes(
        self,
        config: dict[str, Any],
        checkpoint_id: str,
        writes: list[PendingWrite],
    ) -> None:
        """Store pending writes for crash recovery.

        Args:
            config: Dict with ``configurable.thread_id``.
            checkpoint_id: The checkpoint these writes belong to.
            writes: Pending writes to store.
        """
        ...


# ── In-memory checkpoint saver ──────────────────────────────────────────


class InMemorySaver(BaseCheckpointSaver):
    """In-memory checkpoint saver (for development/testing).

    Stores all checkpoints in a thread-safe dict keyed by ``(thread_id, checkpoint_id)``.
    """

    def __init__(self) -> None:
        self._checkpoints: dict[tuple[str, str], tuple[Checkpoint, CheckpointMetadata]] = {}
        self._writes: dict[tuple[str, str], list[PendingWrite]] = {}
        self._lock = threading.Lock()

    def _thread_id(self, config: dict[str, Any]) -> str:
        return config.get("configurable", {}).get("thread_id", "default")

    def _ckpt_id(self, config: dict[str, Any]) -> str | None:
        return config.get("configurable", {}).get("checkpoint_id")

    def get(self, config: dict[str, Any]) -> Checkpoint | None:
        tid = self._thread_id(config)
        cid = self._ckpt_id(config)
        with self._lock:
            if cid:
                entry = self._checkpoints.get((tid, cid))
                return entry[0].copy() if entry else None
            # Return the latest checkpoint for this thread
            latest: Checkpoint | None = None
            for (t, _), (ckpt, _) in self._checkpoints.items():
                if t == tid:
                    if latest is None or ckpt.ts > latest.ts:
                        latest = ckpt
            return latest.copy() if latest else None

    def get_tuple(
        self, config: dict[str, Any]
    ) -> tuple[Checkpoint, list[PendingWrite]] | None:
        ckpt = self.get(config)
        if ckpt is None:
            return None
        tid = self._thread_id(config)
        with self._lock:
            writes = list(self._writes.get((tid, ckpt.id), []))
        return ckpt, writes

    def list(
        self,
        config: dict[str, Any],
        *,
        before: Checkpoint | None = None,
        limit: int = 10,
    ) -> list[Checkpoint]:
        tid = self._thread_id(config)
        with self._lock:
            candidates: list[Checkpoint] = []
            for (t, _), (ckpt, _) in self._checkpoints.items():
                if t == tid:
                    candidates.append(ckpt.copy())

        candidates.sort(key=lambda c: c.ts, reverse=True)

        if before:
            candidates = [c for c in candidates if c.ts < before.ts]

        return candidates[:limit]

    def put(
        self,
        config: dict[str, Any],
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
    ) -> None:
        tid = self._thread_id(config)
        with self._lock:
            self._checkpoints[(tid, checkpoint.id)] = (checkpoint.copy(), metadata)

    def put_writes(
        self,
        config: dict[str, Any],
        checkpoint_id: str,
        writes: list[PendingWrite],
    ) -> None:
        tid = self._thread_id(config)
        with self._lock:
            key = (tid, checkpoint_id)
            if key not in self._writes:
                self._writes[key] = []
            self._writes[key].extend(writes)

    def clear(self) -> None:
        """Clear all checkpoints (useful for testing)."""
        with self._lock:
            self._checkpoints.clear()
            self._writes.clear()


# ── Time travel ─────────────────────────────────────────────────────────


@dataclass
class TimeTravelResult:
    """Result of a time travel operation."""

    checkpoint: Checkpoint
    metadata: CheckpointMetadata
    pending_writes: list[PendingWrite]


class TimeTravel:
    """Provides time travel and replay capabilities over a checkpoint saver.

    Enables:
    - Querying historical checkpoints
    - Replaying execution from a specific checkpoint
    - Branching from a checkpoint
    """

    def __init__(self, saver: BaseCheckpointSaver) -> None:
        self._saver = saver

    def get_history(
        self,
        thread_id: str,
        limit: int = 10,
        before: Checkpoint | None = None,
    ) -> list[TimeTravelResult]:
        """Get checkpoint history for a thread.

        Args:
            thread_id: Thread to query.
            limit: Max entries.
            before: Filter to checkpoints before this one.

        Returns:
            List of ``TimeTravelResult``.
        """
        config = {"configurable": {"thread_id": thread_id}}
        checkpoints = self._saver.list(config, before=before, limit=limit)

        results: list[TimeTravelResult] = []
        for ckpt in checkpoints:
            tuple_result = self._saver.get_tuple(
                {"configurable": {"thread_id": thread_id, "checkpoint_id": ckpt.id}}
            )
            if tuple_result:
                c, pw = tuple_result
                meta = CheckpointMetadata(step=0)  # minimal
                results.append(TimeTravelResult(checkpoint=c, metadata=meta, pending_writes=pw))
        return results

    def replay_from(
        self,
        thread_id: str,
        checkpoint_id: str,
    ) -> tuple[Checkpoint, list[PendingWrite]] | None:
        """Get checkpoint and writes to replay from.

        Args:
            thread_id: Thread ID.
            checkpoint_id: Target checkpoint ID.

        Returns:
            ``(checkpoint, pending_writes)`` or None.
        """
        return self._saver.get_tuple(
            {"configurable": {"thread_id": thread_id, "checkpoint_id": checkpoint_id}}
        )


__all__ = [
    "BaseCheckpointSaver",
    "Checkpoint",
    "CheckpointMetadata",
    "InMemorySaver",
    "PendingWrite",
    "TimeTravel",
    "TimeTravelResult",
]