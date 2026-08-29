"""Dreaming alert checks — heartbeat freshness + queue backlog (no broker).

Phase 6's dreaming pipeline (enqueue-only hook + cold-scan/consolidation) is
processed *out of band*; there is deliberately NO durable message queue (no
Celery/BullMQ — ruling), so an "alerting" check must derive its signals from
data that already exists honestly:

1. **Heartbeat (dreaming-job failures).** The consolidation job (and, when
   ``--heartbeat-file`` is passed, the cold-scan) writes a timestamped heartbeat
   file when it finishes successfully. If that file is missing or its timestamp
   is older than ``max-age-seconds``, the dreaming pipeline is stalled or
   failing → alert.

2. **Backlog (abnormal in-queue count).** Every dreamed thread leaves durable
   Store items carrying a ``thread_id`` field (facts in ``("memories", user)``,
   lessons in ``("system", "lessons")``, conflict markers in
   ``("system", "conflict_markers")`` — see ``dream.py::write_dream_results``).
   Enumerating top-level threads from the checkpointer
   (``loader.py::scan_thread_ids``) and subtracting the set of threads that
   HAVE a dream artifact gives an honest pending-backlog count: threads recorded
   but not yet self-improved. If that count exceeds ``max-backlog`` → alert.

The core logic is pure and fully injectable (clock + state as plain inputs), so
it is deterministically unit-testable. The CLI gathers the real inputs from a
Postgres store+checkpointer and a heartbeat file, then prints findings and
exits non-zero when any check fails:

    python -m src.memory.dreaming.alerts --db-url <url> --heartbeat-file <path>
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Sequence

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore

from src.memory.dreaming.dream import (
    CONFLICT_MARKERS_NAMESPACE,
    LESSONS_NAMESPACE,
)
from src.memory.dreaming.loader import scan_thread_ids

#: Default staleness window for the dreaming heartbeat (seconds).
DEFAULT_MAX_AGE_SECONDS = 3600
#: Default max pending (enqueued-but-not-dreamed) threads.
DEFAULT_MAX_BACKLOG = 50


@dataclass(frozen=True)
class AlertReport:
    """Result of running the dreaming health checks."""

    heartbeat_present: bool
    heartbeat_ok: bool
    backlog_count: int
    backlog_ok: bool
    issues: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """All checks passing — the pipeline is healthy."""
        return self.heartbeat_ok and self.backlog_ok


# --------------------------------------------------------------------------- #
# Pure, injectable core (deterministic; clock + state passed in)               #
# --------------------------------------------------------------------------- #
def write_heartbeat(
    path: str,
    *,
    now: datetime | None = None,
) -> None:
    """Atomically write an ISO-8601 UTC timestamp to ``path``.

    Called by the consolidate (and optionally scan) job after a successful run.
    """
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(stamp)
        f.write("\n")
    os.replace(tmp, path)


def read_heartbeat(path: str) -> datetime | None:
    """Read the last heartbeat timestamp from ``path`` (``None`` if absent)."""
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read().strip()
    except FileNotFoundError:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def is_heartbeat_stale(
    heartbeat: datetime | None,
    *,
    max_age_seconds: int,
    now: datetime | None = None,
) -> bool:
    """True when a heartbeat is absent or older than ``max_age_seconds``."""
    if heartbeat is None:
        return True
    clock = now or datetime.now(timezone.utc)
    age = clock - heartbeat
    return age.total_seconds() > max_age_seconds


def compute_backlog(
    discovered_threads: Sequence[str],
    dreamed_threads: Sequence[str] | set[str],
) -> list[str]:
    """Threads in the checkpointer that have no dream artifact yet."""
    dreamed = set(dreamed_threads)
    return sorted(t for t in discovered_threads if t not in dreamed)


def check_health(
    *,
    heartbeat_ts: datetime | None,
    max_age_seconds: int,
    discovered_threads: Sequence[str],
    dreamed_threads: Sequence[str] | set[str],
    max_backlog: int,
    now: datetime | None = None,
) -> AlertReport:
    """Run both checks over provided state (deterministic, injectable clock).

    Args:
        heartbeat_ts: Last heartbeat timestamp (``None`` = never ran).
        max_age_seconds: Heartbeat staleness window.
        discovered_threads: All top-level threads in the checkpointer.
        dreamed_threads: Threads that have a dream artifact in the Store.
        max_backlog: Max allowed pending (enqueued-but-not-dreamed) threads.
        now: Clock for staleness (injectable for tests).

    Returns:
        An `AlertReport` describing each check's passing state plus the issues
        that must be surfaced to an operator.
    """
    clock = now or datetime.now(timezone.utc)
    heartbeat_present = heartbeat_ts is not None
    heartbeat_ok = not is_heartbeat_stale(
        heartbeat_ts, max_age_seconds=max_age_seconds, now=clock
    )
    backlog = compute_backlog(discovered_threads, dreamed_threads)
    backlog_ok = len(backlog) <= max_backlog

    issues: list[str] = []
    if not heartbeat_ok:
        if heartbeat_present:
            issues.append(
                f"dreaming heartbeat stale (last {heartbeat_ts.isoformat()}, "
                f"older than {max_age_seconds}s) — dreaming pipeline may be down"
            )
        else:
            issues.append(
                "dreaming heartbeat missing — dreaming job has never reported OK"
            )
    if not backlog_ok:
        issues.append(
            f"dreaming backlog too large: {len(backlog)} pending thread(s) "
            f"(limit {max_backlog})"
        )
    return AlertReport(
        heartbeat_present=heartbeat_present,
        heartbeat_ok=heartbeat_ok,
        backlog_count=len(backlog),
        backlog_ok=backlog_ok,
        issues=tuple(issues),
    )


# --------------------------------------------------------------------------- #
# Real-data gathering + CLI                                                      #
# --------------------------------------------------------------------------- #
def discover_dreamed_threads(store: BaseStore) -> set[str]:
    """Threads that have at least one dream artifact in the Store.

    Dreamed facts/lessons/conflicts all carry ``thread_id`` (see
    ``dream.py::write_dream_results``), so the union over the memories prefix
    and the two system namespaces is the durable record of what has been
    self-improved.
    """
    dreamed: set[str] = set()
    for ns in [("memories",), LESSONS_NAMESPACE, CONFLICT_MARKERS_NAMESPACE]:
        for item in store.search(ns):
            tid = item.value.get("thread_id")
            if isinstance(tid, str) and tid:
                dreamed.add(tid)
    return dreamed


def _open_store(db_url: str | None) -> BaseStore:
    from src.memory.store import get_store

    return get_store(db_url)


def _open_checkpointer(db_url: str | None) -> BaseCheckpointSaver:
    from src.memory.checkpointer import get_checkpointer

    return get_checkpointer(db_url)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="alerts", description=__doc__)
    parser.add_argument("--db-url", default=None, help="Postgres URL; defaults to DATABASE_URL env.")
    parser.add_argument(
        "--heartbeat-file",
        default=None,
        help="Path to the dreaming heartbeat file (written by consolidate/scan).",
    )
    parser.add_argument(
        "--max-age-seconds",
        type=int,
        default=DEFAULT_MAX_AGE_SECONDS,
        help=f"Heartbeat staleness window (default {DEFAULT_MAX_AGE_SECONDS}).",
    )
    parser.add_argument(
        "--max-backlog",
        type=int,
        default=DEFAULT_MAX_BACKLOG,
        help=f"Max pending not-yet-dreamed threads (default {DEFAULT_MAX_BACKLOG}).",
    )
    args = parser.parse_args(argv)

    store = _open_store(args.db_url)
    checkpointer = _open_checkpointer(args.db_url)
    try:
        discovered = scan_thread_ids(checkpointer)
        dreamed = discover_dreamed_threads(store)
        heartbeat_ts = read_heartbeat(args.heartbeat_file) if args.heartbeat_file else None

        report = check_health(
            heartbeat_ts=heartbeat_ts,
            max_age_seconds=args.max_age_seconds,
            discovered_threads=discovered,
            dreamed_threads=dreamed,
            max_backlog=args.max_backlog,
        )

        print(f"dreaming alerts (max_age={args.max_age_seconds}s, max_backlog={args.max_backlog})")
        print(
            f"  heartbeat: {'OK' if report.heartbeat_ok else 'STALE/MISSING'} "
            f"(present={report.heartbeat_present})"
        )
        print(
            f"  backlog: {report.backlog_count} pending / limit {args.max_backlog} "
            f"({'OK' if report.backlog_ok else 'OVER'})"
        )
        for issue in report.issues:
            print(f"  ALERT: {issue}")
        print(f"  VERDICT: {'HEALTHY' if report.ok else 'ALERT'}")
        return 0 if report.ok else 1
    finally:
        for handle in (store, checkpointer):
            conn = getattr(handle, "conn", None)
            if conn is not None:
                conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
