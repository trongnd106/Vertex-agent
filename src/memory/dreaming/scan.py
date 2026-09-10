"""Cold-thread dream scan: run the dream over already-finished threads.

The enqueue hook (`src/memory/dreaming/enqueue.py`) only records
``(thread_id, user_id)`` at end-of-turn. This module is the runnable path that
actually *processes* threads — either on demand or as a cron-style cold scan:

- ``scan_thread_ids`` (in `loader.py`) enumerates every top-level thread id
  recorded in a checkpointer.
- :func:`dream_thread` runs the dream graph for one thread.
- ``python -m src.memory.dreaming.scan --user u1 --model openai:gpt-4o-mini``
  scans all threads for the given user and dreams over each (skipping threads
  whose history no longer resolves).

**Documented limitation:** thread ids cannot be mapped back to a user from the
checkpointer alone (the runtime context is not persisted per checkpoint), so
the cold scan requires an explicit ``--user``. The enqueue-hook path does not
have this problem: it captures ``user_id`` at enqueue time.

Celery/BullMQ-style brokers are explicitly out of scope; output is written
directly through the dream graph's store, so repeated runs are idempotent
(keys are content-hash based).
"""

from __future__ import annotations

import argparse
from typing import Any, Sequence

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore

from src.memory.dreaming.dream import DreamState, build_dream_agent
from src.memory.dreaming.loader import scan_thread_ids


def dream_thread(
    *,
    checkpointer: BaseCheckpointSaver,
    store: BaseStore,
    model: str | BaseChatModel,
    thread_id: str,
    user_id: str,
    extractor: Any | None = None,
) -> DreamState:
    """Run the dream graph over one thread for one user; return its result state."""
    graph = build_dream_agent(
        model=model,
        store=store,
        checkpointer=checkpointer,
        extractor=extractor,
    )
    return graph.invoke({"thread_id": thread_id, "user_id": user_id})


def scan_and_dream(
    *,
    checkpointer: BaseCheckpointSaver,
    store: BaseStore,
    model: str | BaseChatModel,
    user_id: str,
    thread_ids: Sequence[str] | None = None,
    extractor: Any | None = None,
) -> dict[str, DreamState]:
    """Dream over every thread (or the given subset) for one user.

    Returns:
        Mapping ``thread_id -> dream result state`` (each state has
        ``facts``/``lessons``/``conflicts`` and possibly ``error``).
    """
    ids = list(thread_ids) if thread_ids is not None else scan_thread_ids(checkpointer)
    results: dict[str, DreamState] = {}
    for thread_id in ids:
        results[thread_id] = dream_thread(
            checkpointer=checkpointer,
            store=store,
            model=model,
            thread_id=thread_id,
            user_id=user_id,
            extractor=extractor,
        )
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scan", description=__doc__)
    parser.add_argument("--db-url", default=None, help=f"Postgres URL; defaults to DATABASE_URL env or {config.DATABASE_URL!r}. Omit for in-memory.")
    parser.add_argument("--user", required=True, help="user_id whose threads to dream (thread_id->user mapping is not persisted).")
    parser.add_argument("--model", default="openai:gpt-4o-mini", help="Cheap extraction model spec.")
    parser.add_argument("--thread-limit", type=int, default=None, help="Only dream over the first N threads (lexicographic).")
    parser.add_argument(
        "--heartbeat-file",
        default=None,
        help="Optional path to write a timestamped heartbeat after a successful run "
        "(consumed by `python -m src.memory.dreaming.alerts`).",
    )
    args = parser.parse_args(argv)

    store = _open_store(args.db_url)
    checkpointer = _open_checkpointer(args.db_url)
    try:
        ids = scan_thread_ids(checkpointer)
        ids = ids[: args.thread_limit] if args.thread_limit else ids
        results = scan_and_dream(
            checkpointer=checkpointer,
            store=store,
            model=args.model,
            user_id=args.user,
            thread_ids=ids,
        )
        for thread_id, state in results.items():
            if "error" in state:
                print(f"[{thread_id}] SKIP: {state['error']}")
            else:
                print(
                    f"[{thread_id}] facts={len(state.get('facts', []))} "
                    f"lessons={len(state.get('lessons', []))} "
                    f"conflicts={len(state.get('conflicts', []))}"
                )
        if args.heartbeat_file:
            from src.memory.dreaming.alerts import write_heartbeat

            write_heartbeat(args.heartbeat_file)
            print(f"heartbeat written to {args.heartbeat_file}")
        return 0
    finally:
        for handle in (store, checkpointer):
            conn = getattr(handle, "conn", None)
            if conn is not None:
                conn.close()


def _open_store(db_url: str | None) -> BaseStore:
    from src.memory.store import get_store

    return get_store(db_url)


def _open_checkpointer(db_url: str | None) -> BaseCheckpointSaver:
    from src.memory.checkpointer import get_checkpointer

    return get_checkpointer(db_url)


if __name__ == "__main__":
    raise SystemExit(main())