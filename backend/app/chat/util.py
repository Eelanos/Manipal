"""
Small, dependency-free helpers: a TTL+LRU cache and a sliding-window rate
limiter. In-process on purpose - one backend instance serves the demo, and a
cache miss only costs one extra model call.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from typing import Any, Optional


class TTLCache:
    """Thread-safe LRU cache whose entries expire after `ttl_s` seconds."""

    def __init__(self, max_size: int, ttl_s: float):
        self.max_size, self.ttl_s = max(0, max_size), ttl_s
        self._d: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        if not self.max_size:
            return None
        now = time.monotonic()
        with self._lock:
            hit = self._d.get(key)
            if hit is None:
                return None
            if now - hit[0] > self.ttl_s:
                del self._d[key]
                return None
            self._d.move_to_end(key)
            return hit[1]

    def put(self, key: str, value: Any) -> None:
        if not self.max_size:
            return
        with self._lock:
            self._d[key] = (time.monotonic(), value)
            self._d.move_to_end(key)
            while len(self._d) > self.max_size:
                self._d.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._d.clear()


class RateLimiter:
    """Sliding one-minute window per client key. limit <= 0 disables it."""

    def __init__(self, limit_per_min: int):
        self.limit = limit_per_min
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        if self.limit <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            if len(self._hits) > 5000:            # bound memory under scans
                for k in [k for k, v in self._hits.items() if not v or now - v[-1] > 60]:
                    self._hits.pop(k, None)
            return True
