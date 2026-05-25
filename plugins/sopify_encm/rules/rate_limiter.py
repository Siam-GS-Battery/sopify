"""Sliding-window rate limiter, one bucket per (rule_id, src) key.

Memory bound: O(rules × sources × requests_in_window). For a 100 req/min cap
with 50 rules and 20 sandboxes that's ~100k timestamps which is fine; if
real workloads need higher, swap deque for a token-bucket counter.

Thread-safe via a single lock — the proxy is async but addon callbacks may
fire from worker threads in mitmproxy.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class _BucketKey:
    rule_id: str
    src: str  # sandbox name / identifier of the requester


class RateLimiter:
    """Per-(rule, source) sliding 60-second window."""

    def __init__(self, window_seconds: float = 60.0) -> None:
        self._window = window_seconds
        self._buckets: dict[_BucketKey, deque[float]] = {}
        self._lock = threading.Lock()

    def check_and_consume(
        self, rule_id: str, src: str, limit_per_min: int | None
    ) -> bool:
        """Return True if a request is allowed; False if the limit is exceeded.

        ``limit_per_min=None`` means unlimited — always allows.
        Consumes one slot on success.
        """
        if limit_per_min is None:
            return True
        now = time.monotonic()
        key = _BucketKey(rule_id=rule_id, src=src)
        with self._lock:
            q = self._buckets.get(key)
            if q is None:
                q = deque()
                self._buckets[key] = q
            # Evict events outside the window before counting — this is what
            # makes it a "sliding" window vs a "fixed minute" reset.
            cutoff = now - self._window
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= limit_per_min:
                return False
            q.append(now)
            return True

    def current_count(self, rule_id: str, src: str) -> int:
        """For audit / dashboard display. Doesn't consume."""
        key = _BucketKey(rule_id=rule_id, src=src)
        now = time.monotonic()
        cutoff = now - self._window
        with self._lock:
            q = self._buckets.get(key)
            if not q:
                return 0
            while q and q[0] < cutoff:
                q.popleft()
            return len(q)

    def reset(self) -> None:
        """Test helper — wipe all buckets."""
        with self._lock:
            self._buckets.clear()
