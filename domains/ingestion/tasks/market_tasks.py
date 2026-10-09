"""
File Overview: Celery task that snapshots the NSE option chain (analysis feed) into TimescaleDB.
Analysis only: nothing here feeds orders. Order-related option data comes from 021's `oc` socket mode.
Uses persistent event loop per worker thread (shared with ingestion_tasks).

All Functions/Classes:
- _fetch_and_store_options_async: symbol -> NSE chain -> TimescaleDB tickdata rows.
- fetch_and_publish_options: Celery task wrapper (name kept for existing callers).

Database Tables: TimescaleDB (tickdata)
"""
import logging
from celery import shared_task
from shared.infrastructure.redis_client import get_redis_client

# Reuse persistent loop from ingestion_tasks
from domains.ingestion.tasks.ingestion_tasks import _get_or_create_loop

logger = logging.getLogger(__name__)


async def _fetch_and_store_options_async(symbol: str):
    from shared.infrastructure.database import get_database_pool
    from datetime import datetime
    from domains.ingestion.infrastructure.outbound.adapter_factory import get_market_data_adapter

    redis = await get_redis_client()
    db_pool = await get_database_pool()
    adapter = get_market_data_adapter(redis_client=redis)

    try:
        dtos = await adapter.fetch_option_chain(symbol)

        if not dtos:
            logger.warning("[%s] No option chain data", symbol)
            return

        underlying = dtos[0].underlying_price
        timestamp = datetime.now()
        db_records = []

        for dto in dtos:
            expiry_date = None
            try:
                expiry_date = datetime.strptime(dto.expiry, "%Y-%m-%d").date()
            except Exception:
                pass
            db_records.append((
                timestamp, symbol, "NSE", dto.option_type, dto.ltp, dto.oi, dto.volume,
                expiry_date, dto.strike, dto.iv, underlying,
            ))

        if db_records:
            async with db_pool.acquire() as conn:
                await conn.copy_records_to_table(
                    'tickdata',
                    records=db_records,
                    columns=[
                        'timestamp', 'symbol', 'exchange', 'instrumenttype', 'lastprice',
                        'openinterest', 'volume', 'expirydate', 'strikeprice', 'impliedvolatility', 'underlyingprice'
                    ]
                )
        logger.debug("[%s] Stored %d option chain rows", symbol, len(db_records))

    except Exception as e:
        logger.error("Error fetching/storing options for %s: %s", symbol, e, exc_info=True)
    finally:
        await adapter.close()


@shared_task(queue='ingestion', name='ingestion.fetch_and_publish_options')
def fetch_and_publish_options(symbol: str = "NIFTY"):
    """Snapshot the NSE option chain for analysis."""
    loop = _get_or_create_loop()
    loop.run_until_complete(_fetch_and_store_options_async(symbol))
