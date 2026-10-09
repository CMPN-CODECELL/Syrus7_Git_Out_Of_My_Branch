"""
Celery job: backfill ~1 year of adjusted daily candles into Timescale for the analysis watchlist.

The watchlist (holdings + open positions, mapped to yfinance tickers) is published to Redis by
the app process, which owns the only 021 login. Celery never talks to 021.
"""
import asyncio
import logging

from shared.infrastructure.celery_app import celery_app

logger = logging.getLogger(__name__)

WATCHLIST_KEY = "kraken:analysis:watchlist"  # hash: analysis key -> yfinance ticker


async def _backfill(items: list[tuple[str, str]], days: int) -> dict:
    from domains.historical.infrastructure.persistence.ohlc_repository import TimescaleOhlcRepository
    from domains.historical.infrastructure.yfinance_daily import fetch_daily_candles
    from shared.infrastructure.database import get_database_pool

    repo = TimescaleOhlcRepository(await get_database_pool())
    done, failed = [], []
    for key, ticker in items:
        try:
            candles = await asyncio.to_thread(fetch_daily_candles, ticker, key, days)
            if not candles:
                failed.append({"key": key, "reason": "empty history"})
                continue
            await repo.save_candles(candles)
            done.append({"key": key, "bars": len(candles)})
        except Exception as exc:
            failed.append({"key": key, "reason": type(exc).__name__})
        await asyncio.sleep(0.5)  # stay polite with yfinance
    logger.info("Daily backfill: %d ok, %d failed", len(done), len(failed))
    return {"ok": done, "failed": failed}


@celery_app.task(name="historical.backfill_daily", queue="analytics")
def backfill_daily(items: list | None = None, days: int | None = None) -> dict:
    from app.config import get_settings
    from domains.ingestion.tasks.ingestion_tasks import _get_or_create_loop
    from shared.infrastructure.redis_client import get_redis_client_sync

    settings = get_settings()
    if items is None:
        raw = get_redis_client_sync().hgetall(WATCHLIST_KEY) or {}
        items = sorted(raw.items())
    pairs = [(str(k), str(v)) for k, v in items if k and v]
    if not pairs:
        return {"ok": [], "failed": [], "note": "watchlist empty"}
    loop = _get_or_create_loop()
    return loop.run_until_complete(_backfill(pairs, days or settings.BackfillDays))
