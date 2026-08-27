from __future__ import annotations

from collections import defaultdict, deque
from threading import RLock
import time


class SlidingWindowRateLimiter:
    def __init__(self, *, limit: int, window_seconds: int) -> None:
        self.limit = int(limit)
        self.window_seconds = int(window_seconds)
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = RLock()

    def allow(self, key: str, *, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else float(now)
        with self._lock:
            q = self._events[key]
            while q and now - q[0] > self.window_seconds:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True
