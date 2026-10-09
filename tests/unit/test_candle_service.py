from datetime import date, datetime, timedelta, timezone

from domains.historical.application.candle_service import CandleService, last_closed_session
from domains.historical.domain.entities import CandleEntity

IST = timezone(timedelta(hours=5, minutes=30))


def bars(key: str, end: date, n: int, start_price: float = 100.0) -> list[CandleEntity]:
    out = []
    day = end
    while len(out) < n:
        if day.weekday() < 5:
            out.append(CandleEntity(key, datetime(day.year, day.month, day.day, tzinfo=timezone.utc), 1, 1, 1, start_price + len(out), 0, "1d"))
        day -= timedelta(days=1)
    return list(reversed(out))


class Repo:
    def __init__(self, candles):
        self.candles = candles
        self.saved = []

    async def get_candles(self, symbol, timeframe="1d", limit=400, end_time=None):
        return list(self.candles)

    async def save_candles(self, candles):
        self.saved.extend(candles)
        return len(candles)


def at(y, m, d, hh, mm):
    return lambda: datetime(y, m, d, hh, mm, tzinfo=IST).astimezone(timezone.utc)


async def test_current_store_is_used_without_live_call():
    calls = []
    now = at(2026, 10, 9, 18, 0)  # Friday after close
    repo = Repo(bars("INFY", date(2026, 10, 9), 60))

    async def factory():
        return repo

    svc = CandleService(factory, lambda *a: calls.append(a) or [], now=now)
    series = await svc.get_daily("INFY", "INFY.NS")
    assert calls == [] and series.source == "timescale" and series.bar_count == 60 and not series.stale


async def test_stale_store_falls_back_to_live_and_saves():
    repo = Repo(bars("INFY", date(2026, 9, 1), 30))

    async def factory():
        return repo

    live = bars("INFY", date(2026, 10, 8), 50)
    svc = CandleService(factory, lambda ticker, key, days: live, now=at(2026, 10, 9, 8, 0))
    series = await svc.get_daily("INFY", "INFY.NS")
    assert series.source == "yfinance" and series.bar_count == 50 and repo.saved == live


async def test_yfinance_down_serves_cache_marked_stale():
    repo = Repo(bars("INFY", date(2026, 9, 1), 30))

    async def factory():
        return repo

    def broken(*_):
        raise ConnectionError("yfinance down")

    svc = CandleService(factory, broken, now=at(2026, 10, 9, 8, 0))
    series = await svc.get_daily("INFY", "INFY.NS")
    assert series.source == "timescale" and series.stale and "failed" in series.error


async def test_no_cache_no_live_is_reported():
    async def factory():
        return None

    def broken(*_):
        raise ConnectionError

    series = await CandleService(factory, broken, now=at(2026, 10, 9, 8, 0)).get_daily("X", "X.NS")
    assert series.bar_count == 0 and series.error


async def test_todays_forming_bar_is_excluded_during_session():
    async def factory():
        return Repo(bars("INFY", date(2026, 10, 9), 40))

    series = await CandleService(factory, None, now=at(2026, 10, 9, 11, 0)).get_daily("INFY", "INFY.NS")
    assert series.excluded_partial_bar and series.as_of == date(2026, 10, 8) and series.bar_count == 39


def test_last_closed_session_skips_weekend():
    assert last_closed_session(datetime(2026, 10, 12, 10, 0, tzinfo=IST)) == date(2026, 10, 9)  # Monday morning
    assert last_closed_session(datetime(2026, 10, 9, 16, 0, tzinfo=IST)) == date(2026, 10, 9)
