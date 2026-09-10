"""Periodic consolidation job for a user's long-term memory namespace.

Idempotent maintenance over ``("memories", <user_id>)``:

1. **Merge duplicates** — items whose *normalized* content is identical are
   merged into the newest entry (its value wins); the older duplicate keys are
   deleted.
2. **Deprioritize stale memories** — items whose ``updated_at`` is older than
   ``stale_after_days`` are lowered one priority tier and stamped with
   ``lowered_at`` (so repeated runs within the same window change nothing —
   idempotent). An item already at the priority floor is flagged ``retracted``
   instead of being deleted (S8 fail-safe: consolidation never removes
   memories).

**Honest limitation (documented):** the Store item model
(`langgraph.store.base.Item`) exposes only ``created_at`` / ``updated_at`` —
there is **no read/access tracking** (verified on `PostgresStore`/`InMemoryStore`:
reads never touch timestamps, `updated_at` bumps only on `put`). "Not read in
N days" is therefore approximated by "not re-written in N days"
(``updated_at``). Only items carrying a ``priority`` field participate in
deprioritization (the dream writes ``priority``; arbitrary user data is left
untouched).

Entrypoint: ``python -m src.memory.dreaming.consolidate [--db-url ...] [--user ...]``
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from langgraph.store.base import BaseStore, Item

#: Priority tiers: fresh dreams are written at this tier (see `dream.py`).
PRIORITY_DEFAULT = 3
PRIORITY_FLOOR = 1
#: Stale item at the floor is flagged `retracted`, never deleted.
RETRACTED_FLAG = "retracted"
LOWERED_AT_FIELD = "lowered_at"

_WS_RE = re.compile(r"\s+")


def normalize_memory_text(value: Any) -> str:
    """Best-effort content normalization for duplicate detection.

    Lowercases and collapses whitespace so "User likes Coffee" and
    "user   likes  coffee" match. Dict values are read from the ``content``
    field when present (dream items), falling back to stable JSON.
    """
    if isinstance(value, dict):
        text = value.get("content")
        if not isinstance(text, str):
            text = json.dumps(value, sort_keys=True, default=str)
    else:
        text = value if isinstance(value, str) else str(value)
    return _WS_RE.sub(" ", text).strip().lower()


@dataclass(frozen=True)
class MemoryRecord:
    """A Store item, copied out for the pure (store-free) consolidation core."""

    key: str
    value: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    #: Only used by ``run_consolidation``/``from_item``; the pure plan core is
    #: namespace-agnostic, so tests may construct records without it.
    namespace: tuple[str, ...] = ()

    @classmethod
    def from_item(cls, item: Item) -> "MemoryRecord":
        return cls(
            key=item.key,
            value=item.value,
            namespace=item.namespace,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )


@dataclass(frozen=True)
class ItemUpdate:
    """Proposed value-field mutations for one surviving item."""

    key: str
    fields: dict[str, Any]


@dataclass(frozen=True)
class ConsolidationPlan:
    """Pure-function output; apply it with :func:`run_consolidation`."""

    merges: tuple[tuple[str, tuple[str, ...]], ...] = ()
    """``(keep_key, keys_to_delete)`` — newest duplicate wins."""
    updates: tuple[ItemUpdate, ...] = ()
    """Priority/retraction mutations for surviving keys only."""

    @property
    def delete_keys(self) -> list[str]:
        return [k for _, deletes in self.merges for k in deletes]

    @property
    def updated_keys(self) -> list[str]:
        return [u.key for u in self.updates]


def plan_consolidation(
    records: Sequence[MemoryRecord],
    *,
    stale_after_days: int,
    now: datetime | None = None,
) -> ConsolidationPlan:
    """Compute the consolidation plan for a set of memory items (pure).

    Pure and deterministic — no Store access — so it is directly unit-testable
    with fabricated timestamps.

    Args:
        records: The items (from one namespace) to consolidate.
        stale_after_days: Aging window; an item whose ``updated_at`` is older
            than this is stale.
        now: Clock for staleness decisions (injectable for tests).

    Returns:
        A `ConsolidationPlan` of duplicate merges + value updates. Never
        proposes deletions of non-duplicate items and never drops an item's
        own key without a duplicate keeper.
    """
    clock = now or datetime.now(timezone.utc)
    window = timedelta(days=stale_after_days)

    # 1) Duplicate detection by normalized content.
    groups: dict[str, list[MemoryRecord]] = {}
    for rec in records:
        groups.setdefault(normalize_memory_text(rec.value), []).append(rec)

    merges: list[tuple[str, tuple[str, ...]]] = []
    doomed: set[str] = set()
    for group in groups.values():
        if len(group) < 2:
            continue
        ordered = sorted(group, key=lambda r: (r.updated_at, r.key), reverse=True)
        keeper = ordered[0]
        deletes = tuple(r.key for r in ordered[1:])
        merges.append((keeper.key, deletes))
        doomed.update(deletes)

    # 2) Staleness deprioritization for surviving (not-merged-away) keys.
    updates: list[ItemUpdate] = []
    for rec in records:
        if rec.key in doomed:
            continue
        value = rec.value
        if PRIORITY_DEFAULT not in value and "priority" not in value:
            # Not a managed memory (no priority field) — leave untouched.
            continue
        priority = value.get("priority")
        if not isinstance(priority, int):
            continue
        if clock - rec.updated_at < window:
            continue  # still fresh in this window
        lowered_at = value.get(LOWERED_AT_FIELD)
        if isinstance(lowered_at, str):
            try:
                stamp = datetime.fromisoformat(lowered_at)
            except ValueError:
                stamp = None
            if stamp is not None and clock - stamp < window:
                continue  # already lowered within this window (idempotency)
        after = max(PRIORITY_FLOOR, priority - 1)
        fields: dict[str, Any] = {
            "priority": after,
            LOWERED_AT_FIELD: clock.isoformat(),
        }
        if priority <= PRIORITY_FLOOR:
            fields[RETRACTED_FLAG] = True
        updates.append(ItemUpdate(key=rec.key, fields=fields))

    return ConsolidationPlan(merges=tuple(merges), updates=tuple(updates))


@dataclass(frozen=True)
class ConsolidationResult:
    """What one `run_consolidation` application actually changed."""

    examined: int = 0
    merged_keys: list[str] = field(default_factory=list)
    deleted_keys: list[str] = field(default_factory=list)
    deprioritized_keys: list[str] = field(default_factory=list)
    retracted_keys: list[str] = field(default_factory=list)
    updated_keys: list[str] = field(default_factory=list)


def run_consolidation(
    store: BaseStore,
    namespace: tuple[str, ...],
    *,
    stale_after_days: int,
    now: datetime | None = None,
) -> ConsolidationResult:
    """Read one namespace, apply the consolidation plan, and report changes.

    Args:
        store: Any ``BaseStore`` (``InMemoryStore`` or ``PostgresStore``).
        namespace: e.g. ``("memories", "user_123")``.
        stale_after_days: Aging window for the de-prioritization rule.
        now: Clock for staleness decisions (injectable for tests).

    Returns:
        A `ConsolidationResult` summarizing the applied changes. Running twice
        back-to-back with the same clock changes nothing (idempotent).
    """
    items = list(store.search(namespace))
    records = [MemoryRecord.from_item(it) for it in items]
    plan = plan_consolidation(records, stale_after_days=stale_after_days, now=now)

    result = ConsolidationResult(examined=len(items))
    for keeper, deletes in plan.merges:
        result.merged_keys.append(keeper)
        for key in deletes:
            store.delete(namespace, key)
            result.deleted_keys.append(key)
    for update in plan.updates:
        item = store.get(namespace, update.key)
        if item is None:
            continue
        value = dict(item.value)
        value.update(update.fields)
        store.put(namespace, update.key, value)
        result.updated_keys.append(update.key)
        if update.fields.get(RETRACTED_FLAG):
            result.retracted_keys.append(update.key)
        else:
            result.deprioritized_keys.append(update.key)
    return result


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: ``python -m src.memory.dreaming.consolidate``."""
    parser = argparse.ArgumentParser(prog="consolidate", description=__doc__)
    parser.add_argument("--db-url", default=None, help=f"Postgres URL; defaults to DATABASE_URL env or {config.DATABASE_URL!r}. Omit for in-memory.")
    parser.add_argument("--user", action="append", default=None, help="user_id(s) to consolidate; defaults to every user found.")
    parser.add_argument("--stale-after-days", type=int, default=30, help="Aging window (default 30).")
    parser.add_argument(
        "--heartbeat-file",
        default=None,
        help="Optional path to write a timestamped heartbeat after a successful run "
        "(consumed by `python -m src.memory.dreaming.alerts`).",
    )
    args = parser.parse_args(argv)

    store = _open_store(args.db_url)
    try:
        namespaces = _namespaces_to_consolidate(store, args.user)
        total = ConsolidationResult()
        for ns in namespaces:
            res = run_consolidation(store, ns, stale_after_days=args.stale_after_days)
            print(f"{ns}: merged={res.merged_keys} deprioritized={res.deprioritized_keys} retracted={res.retracted_keys}")
            total = ConsolidationResult(
                examined=total.examined + res.examined,
                merged_keys=total.merged_keys + res.merged_keys,
                deleted_keys=total.deleted_keys + res.deleted_keys,
                deprioritized_keys=total.deprioritized_keys + res.deprioritized_keys,
                retracted_keys=total.retracted_keys + res.retracted_keys,
                updated_keys=total.updated_keys + res.updated_keys,
            )
        print(f"consolidated {len(namespaces)} namespace(s); {total.examined} items examined")
        if args.heartbeat_file:
            from src.memory.dreaming.alerts import write_heartbeat

            write_heartbeat(args.heartbeat_file)
            print(f"heartbeat written to {args.heartbeat_file}")
        return 0
    finally:
        _close_store(store)


def _open_store(db_url: str | None) -> BaseStore:
    from src.memory.store import get_store

    return get_store(db_url)


def _close_store(store: BaseStore) -> None:
    from src.memory.store import close_store

    close_store(store)


def _namespaces_to_consolidate(store: BaseStore, users: list[str] | None) -> list[tuple[str, ...]]:
    if users:
        return [("memories", user) for user in users]
    # Discover every user namespace present in the store via prefix search.
    discovered: set[str] = set()
    for item in store.search(("memories",)):
        if len(item.namespace) >= 2:
            discovered.add(item.namespace[1])
    return [("memories", user) for user in sorted(discovered)]


if __name__ == "__main__":
    raise SystemExit(main())