"""
Daily candles for the indicator tools: Timescale first (filled by the morning backfill), one
live yfinance fetch as a fallback, and honest metadata on every answer (source, as-of date,
bar count, stale flag, whether today's still-forming bar was excluded).
"""
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Awaitable, Callable, Optional

from domains.historical.domain.entities import CandleEntity

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)

RepoFactory = Callable[[], Awaitable[Optional[object]]]
LiveFetch = Callable[[str, str, int], list[CandleEntity]]


@dataclass
class CandleSeries:
    key: str
    ticker: Optional[str]
    candles: list[CandleEntity] = field(default_factory=list)
    source: str = "none"  # timescale | yfinance | none
    stale: bool = True
    excluded_partial_bar: bool = False
    latest_price: Optional[float] = None  # last yfinance price, may be today's forming bar
    error: Optional[str] = None

    @property
    def closes(self) -> list[float]:
        return [c.close for c in self.candles]

    @property
    def as_of(self) -> Optional[date]:
        return self.candles[-1].timestamp.date() if self.candles else None

    @property
    def bar_count(self) -> int:
        return len(self.candles)


def last_closed_session(now: datetime) -> date:
    """Most recent weekday whose session has closed (exchange holidays are not modelled)."""
    local = now.astimezone(IST)
    day = local.date()
    if local.weekday() < 5 and local.time() >= MARKET_CLOSE:
        return day
    day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def market_is_open(now: datetime) -> bool:
    local = now.astimezone(IST)
    return local.weekday() < 5 and MARKET_OPEN <= local.time() < MARKET_CLOSE


class CandleService:
    def __init__(
        self,
        repo_factory: RepoFactory,
        live_fetch: Optional[LiveFetch],
        *,
        days: int = 400,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        live_timeout: float = 15.0,
    ):
        self._repo_factory = repo_factory
        self._live_fetch = live_fetch
        self._days = days
        self._now = now
        self._live_timeout = live_timeout

    async def _repo(self):
        try:
            return await self._repo_factory()
        except Exception as exc:
            logger.debug("OHLC repository unavailable: %s", exc)
            return None

    async def get_daily(self, key: str, ticker: Optional[str], *, allow_live: bool = True) -> CandleSeries:
        series = CandleSeries(key=key, ticker=ticker)
        now = self._now()
        expected = last_closed_session(now)

        repo = await self._repo()
        stored: list[CandleEntity] = []
        if repo is not None:
            try:
                stored = await repo.get_candles(key, timeframe="1d", limit=self._days)
            except Exception as exc:
                logger.warning("Reading candles for %s failed: %s", key, exc)

        # Tolerate weekends/holidays: data is current if it reaches within 4 days of the last session.
        stored_current = bool(stored) and stored[-1].timestamp.date() >= expected - timedelta(days=4)

        live: list[CandleEntity] = []
        if not stored_current and allow_live and ticker and self._live_fetch is not None:
            try:
                live = await asyncio.wait_for(
                    asyncio.to_thread(self._live_fetch, ticker, key, self._days), timeout=self._live_timeout
                )
            except Exception as exc:
                series.error = f"live history fetch failed: {type(exc).__name__}"
                logger.warning("yfinance history for %s failed: %s", ticker, exc)
            if live and repo is not None:
                try:
                    await repo.save_candles(live)
                except Exception as exc:
                    logger.debug("Saving fetched candles for %s failed: %s", key, exc)

        if live:
            candles, series.source = live, "yfinance"
        elif stored:
            candles, series.source = stored, "timescale"
        else:
            if series.error is None:
                series.error = "no daily history available" if ticker else "no yfinance mapping for this instrument"
            return series

        series.latest_price = candles[-1].close
        # Indicators use closed bars only: drop today's bar while the session is still running.
        today = now.astimezone(IST).date()
        if candles and candles[-1].timestamp.date() == today and not (now.astimezone(IST).time() >= MARKET_CLOSE):
            candles = candles[:-1]
            series.excluded_partial_bar = True
        series.candles = candles
        series.stale = not candles or candles[-1].timestamp.date() < expected - timedelta(days=4)
        return series
