"""Token-bucket rate limiter per user.

Thread-safe via ``threading.Lock``.  The injectable ``time_function``
lets tests advance time without sleeping.
"""

from __future__ import annotations

import threading
import time
from typing import Callable


class RateLimiter:
    """Token-bucket rate limiter.

    Each call to ``allow()`` draws one token per *cost*.  When the
    bucket is empty the request is denied.

    Args:
        capacity: Maximum tokens (burst limit).
        refill_rate: Tokens added per second.
        time_function: Callable returning seconds (default ``time.time``).
    """

    def __init__(
        self,
        capacity: float = 60,
        refill_rate: float = 1.0,
        time_function: Callable[[], float] = time.time,
    ) -> None:
        self.capacity = capacity
        self.refill_rate = refill_rate
        self._time_func = time_function
        self._buckets: dict[str, float] = {}
        self._timestamps: dict[str, float] = {}
        self._lock = threading.Lock()

    def _refill(self, key: str) -> float:
        """Refill the bucket for *key* and return current tokens."""
        now = self._time_func()
        tokens = self._buckets.get(key, self.capacity)
        last = self._timestamps.get(key, now)
        elapsed = now - last
        tokens = min(self.capacity, tokens + elapsed * self.refill_rate)
        self._buckets[key] = tokens
        self._timestamps[key] = now
        return tokens

    def allow(self, key: str, cost: float = 1.0) -> tuple[bool, float]:
        """Check if request for *key* is allowed.

        Returns:
            (allowed, remaining_tokens).
        """
        with self._lock:
            tokens = self._refill(key)
            if tokens >= cost:
                self._buckets[key] = tokens - cost
                return True, self._buckets[key]
            return False, tokens

    def reset(self, key: str) -> None:
        """Reset the bucket for *key* (for testing)."""
        with self._lock:
            self._buckets.pop(key, None)
            self._timestamps.pop(key, None)