"""Stale-thread cleanup job for the Postgres checkpointer.

The ``PostgresSaver`` checkpointer has no built-in TTL (unlike a Redis-backed
checkpointer), so short-term sessions accumulate in the ``checkpoints`` /
``checkpoint_blobs`` / ``checkpoint_writes`` tables indefinitely. This module
implements a small admin job that finds thread_ids whose **most recent**
checkpoint activity is older than ``max_age_days`` and deletes them.

Staleness derivation (relies on the real installed schema, see below):

- ``langgraph/checkpoint/postgres/base.py`` defines the ``checkpoints`` table:
  columns ``thread_id``, ``checkpoint_ns``, ``checkpoint_id``,
  ``parent_checkpoint_id``, ``type``, ``checkpoint JSONB``, ``metadata JSONB``.
  There is **no per-thread ``created_at`` column**.
- Every checkpoint JSONB carries a ``ts`` key (an ISO-8601 UTC timestamp,
  e.g. ``2026-08-28T00:22:49.994780+00:00``) written by LangGraph when the
  checkpoint is created. A thread's "last activity" is therefore the maximum
  ``checkpoint->>'ts'`` across all of its rows.

        SELECT thread_id
        FROM checkpoints
        GROUP BY thread_id
        HAVING MAX((checkpoint->>'ts')::timestamptz) < %s

  ((…)::timestamptz makes the ISO timestamp comparison timezone-safe.)

Deletion uses the checkpointer's real public ``delete_thread(thread_id)`` API
(``postgres/__init__.py``), which removes the thread from all three tables
(``checkpoints``, ``checkpoint_blobs``, ``checkpoint_writes``). A ``checkpointer``
is therefore preferred; if none is supplied the job falls back to raw SQL
deletes on the same three tables via the supplied connection.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence

import psycopg
from langgraph.checkpoint.base import BaseCheckpointSaver
from psycopg.rows import dict_row

DEFAULT_MAX_AGE_DAYS = 30

# No FK constraints between these tables, so deletion order is not significant.
_DELETE_SQL = {
    "checkpoints": "DELETE FROM checkpoints WHERE thread_id = %s",
    "checkpoint_blobs": "DELETE FROM checkpoint_blobs WHERE thread_id = %s",
    "checkpoint_writes": "DELETE FROM checkpoint_writes WHERE thread_id = %s",
}


def _stale_thread_ids(
    connection: psycopg.Connection, *, max_age_days: int
) -> list[str]:
    import datetime as _dt

    cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=max_age_days)
    sql = (
        "SELECT thread_id FROM checkpoints "
        "GROUP BY thread_id "
        "HAVING MAX((checkpoint->>'ts')::timestamptz) < %s "
        "ORDER BY thread_id"
    )
    with connection.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (cutoff,))
        return [row["thread_id"] for row in cur.fetchall()]


def cleanup_stale_threads(
    connection: psycopg.Connection,
    *,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    dry_run: bool = False,
    checkpointer: BaseCheckpointSaver | None = None,
) -> list[str]:
    """Delete thread_ids inactive for more than ``max_age_days`` days.

    Args:
        connection: psycopg Connection to the checkpointer's database (used for
            the staleness SELECT, and for raw-SQL deletion when ``checkpointer``
            is ``None``).
        max_age_days: inactivity threshold in days.
        dry_run: if ``True``, only report thread_ids, do not delete them.
        checkpointer: optional checkpointer whose ``delete_thread`` is used for
            the actual deletion (the real public delete API).

    Returns:
        The list of thread_ids that are stale (and, when ``not dry_run``, that
        were deleted).
    """
    thread_ids = _stale_thread_ids(connection, max_age_days=max_age_days)
    if dry_run:
        return thread_ids
    for thread_id in thread_ids:
        if checkpointer is not None:
            checkpointer.delete_thread(thread_id)
        else:
            _delete_thread_sql(connection, thread_id)
    return thread_ids


def _delete_thread_sql(connection: psycopg.Connection, thread_id: str) -> None:
    """Raw-SQL fallback deleting a thread from all three tables."""
    with connection.cursor() as cur:
        for sql in _DELETE_SQL.values():
            cur.execute(sql, (thread_id,))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Delete short-term session threads inactive for N days "
        "from the Postgres checkpointer."
    )
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=DEFAULT_MAX_AGE_DAYS,
        help=f"Delete threads inactive for more than this many days (default: "
        f"{DEFAULT_MAX_AGE_DAYS}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only list stale thread_ids, do not delete anything.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Postgres connection string (defaults to the DATABASE_URL env var).",
    )
    args = parser.parse_args(argv)

    url = args.database_url or os.environ.get("DATABASE_URL")
    if not url:
        parser.error("DATABASE_URL is required (or pass --database-url).")

    from src.memory.checkpointer import get_checkpointer

    checkpointer = get_checkpointer(url)
    try:
        deleted = cleanup_stale_threads(
            checkpointer.conn,
            max_age_days=args.max_age_days,
            dry_run=args.dry_run,
            checkpointer=checkpointer,
        )
    finally:
        checkpointer.conn.close()

    verb = "Would delete" if args.dry_run else "Deleted"
    print(f"{verb} {len(deleted)} stale thread_id(s):")
    for thread_id in deleted:
        print(f"  {thread_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["cleanup_stale_threads", "main"]
