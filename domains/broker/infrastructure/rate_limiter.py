"""Async token-bucket rate limiter shared by every 021 REST call."""
import asyncio
import time
from typing import Awaitable, Callable


class TokenBucket:
    def __init__(
        self,
        rate_per_second: float,
        burst: int | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        if rate_per_second <= 0:
            raise ValueError("rate_per_second must be positive")
        self._rate = rate_per_second
        self._capacity = float(burst if burst is not None else max(1, int(rate_per_second)))
        self._tokens = self._capacity
        self._clock = clock
        self._sleep = sleep
        self._updated = clock()
        self._lock = asyncio.Lock()
        self._blocked_until = 0.0

    def _refill(self) -> None:
        now = self._clock()
        self._tokens = min(self._capacity, self._tokens + (now - self._updated) * self._rate)
        self._updated = now

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = self._clock()
                if now < self._blocked_until:
                    await self._sleep(self._blocked_until - now)
                    continue
                self._refill()
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                await self._sleep((1 - self._tokens) / self._rate)

    def penalize(self, seconds: float) -> None:
        """After a 429, stop everyone for `seconds` instead of letting each caller hammer 021."""
        self._blocked_until = max(self._blocked_until, self._clock() + max(0.0, seconds))
        self._tokens = 0.0
