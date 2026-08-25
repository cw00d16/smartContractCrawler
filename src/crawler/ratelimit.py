from __future__ import annotations

import threading
import time


class RateLimiter:
    """Shared min-interval limiter so every caller against one explorer API
    queue behind a single clock, instead of each resolver limiting itself."""

    def __init__(self, calls_per_second: float):
        self._min_interval = 1.0 / calls_per_second
        self._lock = threading.Lock()
        self._last_call = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            remaining = self._min_interval - (now - self._last_call)
            if remaining > 0:
                time.sleep(remaining)
            self._last_call = time.monotonic()
