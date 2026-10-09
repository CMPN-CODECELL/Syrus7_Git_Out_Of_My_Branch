"""Daily OHLC history from yfinance (adjusted for splits/bonuses/dividends). Analysis only."""
import logging
from datetime import date, datetime, timedelta, timezone

from domains.historical.domain.entities import CandleEntity

logger = logging.getLogger(__name__)


def fetch_daily_candles(ticker: str, analysis_key: str, days: int) -> list[CandleEntity]:
    """Blocking call; run it in a thread. Raises on network errors; returns [] for empty frames."""
    import yfinance as yf

    start = date.today() - timedelta(days=days)
    frame = yf.Ticker(ticker).history(start=start.isoformat(), interval="1d", auto_adjust=True)
    if frame is None or frame.empty:
        return []
    candles: list[CandleEntity] = []
    for ts, row in frame.iterrows():
        try:
            day = ts.date() if hasattr(ts, "date") else ts
            candles.append(CandleEntity(
                symbol=analysis_key,
                timestamp=datetime(day.year, day.month, day.day, tzinfo=timezone.utc),
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=int(row.get("Volume", 0) or 0),
                timeframe="1d",
            ))
        except (KeyError, TypeError, ValueError):
            continue
    return candles
