"""Phase 7: token-bucket rate limiter tests (Ruling M4 — library + CLI demo).

Covers bucket refill over time, burst capping, per-user independence, no
negative tokens, thread-safety under contention, and the deterministic CLI demo
path (`python -m src.api.rate_limit`).
"""

from __future__ import annotations

import threading

import pytest

from src.api.rate_limit import RateLimiter

# No mutable shared state: each test builds its own limiter + fake clock.
class FakeClock:
    def __init__(self, start: float = 0.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_limiter(capacity=5.0, refill_rate=1.0, clock=None):
    clock = clock or FakeClock()
    return RateLimiter(capacity=capacity, refill_rate=refill_rate, time_fn=clock), clock


def test_burst_capped_at_capacity():
    limiter, _ = make_limiter(capacity=3.0, refill_rate=10.0)
    outcomes = [limiter.allow("u1") for _ in range(5)]
    assert outcomes == [True, True, True, False, False], "burst must stop at capacity"
    assert limiter.tokens("u1") == 0.0


def test_bucket_refills_over_time():
    limiter, clock = make_limiter(capacity=5.0, refill_rate=2.0)
    assert [limiter.allow("u1") for _ in range(5)] == [True] * 5
    assert limiter.allow("u1") is False  # empty

    clock.advance(1.0)  # -> +2 tokens after 1s
    assert limiter.tokens("u1") == 2.0
    assert limiter.allow("u1") is True
    assert limiter.allow("u1") is True
    assert limiter.allow("u1") is False, "only 2 tokens refilled"

    # Refill is capped at capacity, never above.
    clock.advance(100.0)
    assert limiter.tokens("u1") == 5.0


def test_capacity_never_rebounds_above_capacity():
    limiter, clock = make_limiter(capacity=4.0, refill_rate=1.0)
    clock.advance(10.0)
    # Bucket untouched for 10s but still capped at 4 existing tokens.
    assert limiter.allow("u1") is True
    assert limiter.tokens("u1") == 3.0


def test_different_users_independent():
    limiter, clock = make_limiter(capacity=2.0, refill_rate=1.0)
    assert limiter.allow("alice") is True
    assert limiter.allow("alice") is True
    assert limiter.allow("alice") is False  # alice drained
    assert limiter.allow("bob") is True, "bob has a fresh bucket"
    assert limiter.allow("bob") is True
    clock.advance(2.0)
    assert limiter.allow("alice") is True, (
        "alice refilled; bob untouched but independent"
    )


def test_no_negative_tokens():
    limiter, clock = make_limiter(capacity=2.0, refill_rate=1.0)
    for _ in range(100):  # hammer long after the bucket is empty
        limiter.allow("u1")
    clock.advance(0.5)
    assert limiter.tokens("u1") >= 0.0, "tokens must never go negative"


def test_zero_and_negative_cost_rejected():
    limiter, _ = make_limiter()
    with pytest.raises(ValueError):
        limiter.allow("u1", cost=0)
    with pytest.raises(ValueError):
        limiter.allow("u1", cost=-1.0)


def test_invalid_config_rejected():
    with pytest.raises(ValueError):
        RateLimiter(capacity=0, refill_rate=1.0)
    with pytest.raises(ValueError):
        RateLimiter(capacity=1.0, refill_rate=0)


def test_cost_larger_than_capacity_denied():
    limiter, _ = make_limiter(capacity=3.0)
    assert limiter.allow("u1", cost=5.0) is False
    assert limiter.tokens("u1") == 3.0, "failed consume must not spend tokens"


def test_injectable_clock_drives_behavior():
    limiter, clock = make_limiter(capacity=1.0, refill_rate=1.0)
    assert limiter.allow("u1") is True
    assert limiter.allow("u1") is False
    clock.advance(1.0)
    assert limiter.allow("u1") is True, "exactly one token after 1s at 1/s"
    assert limiter.allow("u1") is False


def test_reset_drops_buckets():
    limiter, _ = make_limiter(capacity=2.0)
    limiter.allow("u1")
    limiter.allow("u1")
    assert limiter.allow("u1") is False
    limiter.reset()
    assert limiter.allow("u1") is True, "post-reset bucket is full again"


def test_concurrent_allows_do_not_overspend():
    # 5 tokens, 10 threads racing 10 calls each with a FROZEN clock (elapsed
    # time is always 0, so no refill). Total allowed must never exceed capacity.
    limiter, _ = make_limiter(capacity=5.0, refill_rate=1.0)
    results: list[bool] = []
    results_lock = threading.Lock()

    def worker():
        for _ in range(10):
            ok = limiter.allow("u1")
            with results_lock:
                results.append(ok)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sum(results) == 5, "lock+token logic must cap concurrent calls at capacity"
    assert limiter.tokens("u1") == 0.0


def test_cli_demo_runs_and_throttles(tmp_path, capsys):
    from src.api import rate_limit as mod

    rc = mod.main(
        ["--capacity", "2", "--refill-rate", "1", "--burst", "6", "--users", "2"]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "user-1" in out and "user-2" in out
    # With capacity 2 and no meaningful refill between calls, later calls deny.
    assert "DENIED" in out