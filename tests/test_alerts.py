"""Phase 8: dreaming alert checks — deterministic unit tests.

The alert logic in ``src/memory/dreaming/alerts.py`` is a pure, injectable
function of (clock, state): heartbeat timestamp + thread discovery sets. All
tests here use fabricated state and an explicit ``now`` — no DB, no network.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from langgraph.store.memory import InMemoryStore

from src.memory.dreaming.alerts import (
    compute_backlog,
    is_heartbeat_stale,
    read_heartbeat,
    write_heartbeat,
)
from src.memory.dreaming.dream import LESSONS_NAMESPACE, memories_namespace

NOW = datetime(2026, 8, 29, 12, 0, 0, tzinfo=timezone.utc)


def _ts(**delta):
    return NOW + timedelta(**delta)


# --------------------------------------------------------------------------- #
# Heartbeat staleness                                                           #
# --------------------------------------------------------------------------- #
def test_heartbeat_missing_is_stale():
    assert is_heartbeat_stale(None, max_age_seconds=3600, now=NOW)


def test_heartbeat_within_window_is_fresh():
    assert not is_heartbeat_stale(
        _ts(seconds=-60), max_age_seconds=3600, now=NOW
    )


def test_heartbeat_older_than_window_is_stale():
    assert is_heartbeat_stale(
        _ts(seconds=-3601), max_age_seconds=3600, now=NOW
    )


def test_heartbeat_write_and_read_roundtrip(tmp_path):
    path = str(tmp_path / "heartbeat")
    assert read_heartbeat(path) is None  # absent -> None
    write_heartbeat(path, now=NOW)
    assert read_heartbeat(path) == NOW


# --------------------------------------------------------------------------- #
# Backlog                                                                        #
# --------------------------------------------------------------------------- #
def test_backlog_counts_only_undreamed_threads():
    discovered = ["t1", "t2", "t3"]
    dreamed = {"t1", "t3"}
    assert compute_backlog(discovered, dreamed) == ["t2"]


def test_backlog_empty_when_all_dreamed():
    assert compute_backlog(["a", "b"], ["a", "b"]) == []


# --------------------------------------------------------------------------- #
# Full health check                                                              #
# --------------------------------------------------------------------------- #
def test_health_ok_when_heartbeat_fresh_and_within_backlog():
    from src.memory.dreaming.alerts import check_health

    report = check_health(
        heartbeat_ts=_ts(seconds=-30),
        max_age_seconds=3600,
        discovered_threads=["t1", "t2"],
        dreamed_threads={"t1", "t2"},
        max_backlog=0,
        now=NOW,
    )
    assert report.ok
    assert report.heartbeat_ok
    assert report.backlog_ok
    assert report.issues == ()


def test_health_alerts_stale_heartbeat():
    from src.memory.dreaming.alerts import check_health

    report = check_health(
        heartbeat_ts=_ts(seconds=-7200),
        max_age_seconds=3600,
        discovered_threads=[],
        dreamed_threads=set(),
        max_backlog=10,
        now=NOW,
    )
    assert not report.ok
    assert not report.heartbeat_ok
    assert report.backlog_ok
    assert any("stale" in i for i in report.issues)


def test_health_alerts_missing_heartbeat():
    from src.memory.dreaming.alerts import check_health

    report = check_health(
        heartbeat_ts=None,
        max_age_seconds=3600,
        discovered_threads=[],
        dreamed_threads=set(),
        max_backlog=10,
        now=NOW,
    )
    assert not report.ok
    assert not report.heartbeat_present
    assert any("missing" in i for i in report.issues)


def test_health_alerts_backlog_over_threshold():
    from src.memory.dreaming.alerts import check_health

    report = check_health(
        heartbeat_ts=_ts(seconds=-10),
        max_age_seconds=3600,
        discovered_threads=[f"t{i}" for i in range(5)],
        dreamed_threads=set(),
        max_backlog=2,
        now=NOW,
    )
    assert not report.ok
    assert not report.backlog_ok
    assert report.backlog_count == 5
    assert any("backlog" in i for i in report.issues)


def test_health_alerts_both_when_all_bad():
    from src.memory.dreaming.alerts import check_health

    report = check_health(
        heartbeat_ts=None,
        max_age_seconds=3600,
        discovered_threads=["t1", "t2"],
        dreamed_threads=set(),
        max_backlog=1,
        now=NOW,
    )
    assert not report.heartbeat_ok
    assert not report.backlog_ok
    assert len(report.issues) == 2


# --------------------------------------------------------------------------- #
# Dreamed-thread discovery from a real (in-memory) Store                         #
# --------------------------------------------------------------------------- #
def test_discover_dreamed_threads_from_store_artifacts():
    from src.memory.dreaming.alerts import discover_dreamed_threads

    store = InMemoryStore()
    # A dreamed fact carries thread_id in the user's memory namespace.
    store.put(memories_namespace("u1"), "fact-k1",
              {"kind": "fact", "content": "x", "thread_id": "t-fact", "priority": 3})
    # A lesson carries thread_id in the lessons namespace.
    store.put(LESSONS_NAMESPACE, "lesson-k1",
              {"kind": "lesson", "content": "y", "thread_id": "t-lesson"})
    # Non-dream data (no thread_id) is ignored.
    store.put(memories_namespace("u1"), "manual",
              {"kind": "fact", "content": "z", "priority": 3})

    assert discover_dreamed_threads(store) == {"t-fact", "t-lesson"}


def test_discover_dreamed_threads_exceeds_default_search_page_size():
    from src.memory.dreaming.alerts import discover_dreamed_threads

    # BaseStore.search defaults to limit=10, so seed >10 items in one namespace
    # across many threads: if pagination regresses, threads with artifacts past
    # page 1 are treated as undreamed and the backlog inflates.
    store = InMemoryStore()
    for i in range(15):
        store.put(memories_namespace(f"u{i % 3}"), f"fact-{i}",
                  {"kind": "fact", "content": f"c{i}", "thread_id": f"t-{i}", "priority": 3})
    store.put(LESSONS_NAMESPACE, "lesson-k1",
              {"kind": "lesson", "content": "y", "thread_id": "t-lesson"})

    assert discover_dreamed_threads(store) == {f"t-{i}" for i in range(15)} | {"t-lesson"}
