from __future__ import annotations

import asyncio
import time
from collections import deque


class QueryRateLimiter:
    """Enforce CRAFT execute_query limit of 10 calls per minute."""

    def __init__(
        self,
        max_calls: int = 10,
        window_s: float = 60.0,
        min_interval_s: float = 6.0,
    ):
        self.max_calls = max_calls
        self.window_s = window_s
        self.min_interval_s = min_interval_s
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()
        self._last_call = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            while self._timestamps and now - self._timestamps[0] > self.window_s:
                self._timestamps.popleft()

            if self._last_call:
                wait_interval = self.min_interval_s - (now - self._last_call)
                if wait_interval > 0:
                    await asyncio.sleep(wait_interval)
                    now = time.monotonic()

            if len(self._timestamps) >= self.max_calls:
                sleep_for = self.window_s - (now - self._timestamps[0]) + 0.05
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)
                    now = time.monotonic()
                    while self._timestamps and now - self._timestamps[0] > self.window_s:
                        self._timestamps.popleft()

            self._timestamps.append(time.monotonic())
            self._last_call = time.monotonic()
