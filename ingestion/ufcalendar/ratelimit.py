"""Client-side rate limiting."""

from __future__ import annotations

import time
from collections import deque
from typing import Callable


class SlidingWindowLimiter:
    """Allow at most `max_calls` in any rolling `period` seconds."""

    def __init__(
        self,
        max_calls: int,
        period: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_calls < 1:
            raise ValueError("max_calls must be >= 1")
        self.max_calls = max_calls
        self.period = period
        self._clock = clock
        self._sleep = sleep
        self._calls: deque[float] = deque()

    def acquire(self) -> float:
        """Block until a call is allowed, record it, and return seconds waited."""
        waited = 0.0
        while True:
            now = self._clock()
            while self._calls and now - self._calls[0] >= self.period:
                self._calls.popleft()
            if len(self._calls) < self.max_calls:
                self._calls.append(now)
                return waited
            wait = self.period - (now - self._calls[0])
            self._sleep(wait)
            waited += wait
