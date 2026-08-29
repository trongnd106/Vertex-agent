"""Per-``user_id`` token-bucket rate limiter (Ruling M4: library + CLI demo only).

Phase 7 scopes this module to a **thin, tested library**: a token-bucket rate
limiter keyed by ``user_id`` plus a callable CLI demo. There is deliberately NO
web server, FastAPI/Flask service, or API Gateway — the plan's "API Gateway"
layer stays out of scope for phases 0-8. Deployments that later add an HTTP
front door can call :meth:`RateLimiter.allow(user_id, ...)` from that layer.

The token-bucket algorithm:

- Each ``user_id`` owns a bucket holding up to ``capacity`` tokens (the allowed
  burst size).
- Tokens refill continuously at ``refill_rate`` tokens/second, capped at
  ``capacity``.
- ``allow(user_id)`` consumes one token (or ``cost`` tokens) when available and
  returns ``True``; otherwise it returns ``False`` — the caller decides how to
  surface the denial (HTTP 429, queue, backoff, ...). Tokens never go negative.
- The clock is **injectable** (``time_fn``), so tests are fully deterministic;
  production uses ``time.monotonic`` by default.
- All bucket state is guarded by a single ``threading.Lock``, so concurrent
  callers (e.g. workers in a process) cannot overspend a bucket.

Demo:

    python -m src.api.rate_limit --capacity 5 --refill-rate 1 --burst 20 --users 2

    prints a simulated burst for two users and shows each one being throttled
    once its bucket empties (deterministic: steps an internal fake clock).
"""

from __future__ import annotations

import argparse
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

#: Type of the injectable time source. Returns an arbitrary strictly-increasing
#: number of seconds (``time.monotonic`` in production).
TimeFn = Callable[[], float]


@dataclass
class _Bucket:
    """Mutable per-user token state (guarded by the limiter's lock)."""

    tokens: float
    updated: float


class RateLimiter:
    """Token-bucket rate limiter keyed by ``user_id``.

    Args:
        capacity: Maximum tokens per bucket, i.e. the burst size. Must be > 0.
        refill_rate: Tokens refilled per second. Must be > 0.
        time_fn: Callable returning the current time in seconds. Defaults to
            ``time.monotonic``; tests inject a fake clock for determinism.
    """

    def __init__(
        self,
        *,
        capacity: float,
        refill_rate: float,
        time_fn: TimeFn = time.monotonic,
    ) -> None:
        if capacity <= 0:
            raise ValueError(f"capacity must be > 0, got {capacity}")
        if refill_rate <= 0:
            raise ValueError(f"refill_rate must be > 0, got {refill_rate}")
        self._capacity = float(capacity)
        self._refill_rate = float(refill_rate)
        self._time_fn = time_fn
        self._lock = threading.Lock()
        self._buckets: dict[str, _Bucket] = {}

    # ------------------------------------------------------------------ #
    # Public API                                                         #
    # ------------------------------------------------------------------ #
    def allow(self, user_id: str, cost: float = 1.0) -> bool:
        """Try to consume ``cost`` tokens for ``user_id``.

        Refills the user's bucket for the elapsed time first, then consumes if
        enough tokens remain. Returns ``True`` when the call is within budget,
        ``False`` when the bucket is empty (i.e. the user is throttled). Is
        thread-safe: concurrent ``allow`` calls for the same user share one
        bucket under a lock.
        """
        if cost <= 0:
            raise ValueError(f"cost must be > 0, got {cost}")
        now = self._time_fn()
        with self._lock:
            bucket = self._buckets.setdefault(
                user_id, _Bucket(tokens=self._capacity, updated=now)
            )
            self._refill(bucket, now)
            if bucket.tokens >= cost:
                bucket.tokens -= cost
                return True
            return False

    def tokens(self, user_id: str) -> float:
        """Return the current (refill-adjusted) token count for ``user_id``."""
        now = self._time_fn()
        with self._lock:
            bucket = self._buckets.get(user_id)
            if bucket is None:
                return self._capacity
            self._refill(bucket, now)
            return bucket.tokens

    def reset(self) -> None:
        """Drop every user's bucket (used by tests and the CLI demo)."""
        with self._lock:
            self._buckets.clear()

    # ------------------------------------------------------------------ #
    # Internal                                                           #
    # ------------------------------------------------------------------ #
    def _refill(self, bucket: _Bucket, now: float) -> None:
        """Top a bucket up to ``capacity`` after ``now - bucket.updated`` s."""
        # Caller holds `self._lock`.
        elapsed = now - bucket.updated
        if elapsed > 0:
            bucket.tokens = min(
                self._capacity, bucket.tokens + elapsed * self._refill_rate
            )
            bucket.updated = now

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"RateLimiter(capacity={self._capacity:g}, "
            f"refill_rate={self._refill_rate:g})"
        )


class _FakeClock:
    """Deterministic clock for the CLI demo: steps by a fixed interval."""

    def __init__(self, step: float) -> None:
        self._now = 0.0
        self._step = step

    def __call__(self) -> float:
        """Advance the clock by `step` and return the new time."""
        self._now += self._step
        return self._now


def main(argv: Sequence[str] | None = None) -> int:
    """Simulate a per-user burst being throttled; stdlib-only demo.

    Two users hit the limiter with the same load. Real time is NOT used — the
    demo steps an injected ``_FakeClock`` so the output is reproducible. Each
    ``allow`` call advances the clock by ``--interval`` seconds, letting the
    token bucket refill a little between calls.
    """
    parser = argparse.ArgumentParser(
        description="Token-bucket rate-limit demo: show a burst being "
        "throttled per user_id (deterministic fake clock, stdlib only)."
    )
    parser.add_argument(
        "--capacity", type=float, default=5.0, help="Burst size (tokens per bucket)."
    )
    parser.add_argument(
        "--refill-rate",
        type=float,
        default=1.0,
        help="Tokens refilled per second.",
    )
    parser.add_argument(
        "--burst", type=int, default=20, help="Calls each simulated user makes."
    )
    parser.add_argument(
        "--users", type=int, default=2, help="Number of simulated user_ids."
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0.1,
        help="Simulated seconds between calls.",
    )
    args = parser.parse_args(argv)

    limiter = RateLimiter(
        capacity=args.capacity,
        refill_rate=args.refill_rate,
        time_fn=_FakeClock(step=args.interval),
    )
    users = [f"user-{i}" for i in range(1, args.users + 1)]

    print(
        f"RateLimiter(capacity={args.capacity:g}, "
        f"refill_rate={args.refill_rate:g}/s)"
    )
    print(
        f"{args.users} user(s) x {args.burst} calls, clock steps "
        f"{args.interval:g}s between calls\n"
    )
    allowed = {u: 0 for u in users}
    for attempt in range(1, args.burst + 1):
        for user in users:
            ok = limiter.allow(user)
            allowed[user] += ok
            print(
                f"{user:>7} call {attempt:>3}: {'ALLOWED' if ok else 'DENIED '}  "
                f"tokens={limiter.tokens(user):.2f}"
            )
        print()

    print("Summary:")
    for user in users:
        denied = args.burst - allowed[user]
        print(f"  {user:>7}: {allowed[user]:>3}/{args.burst} allowed, {denied} denied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["RateLimiter"]