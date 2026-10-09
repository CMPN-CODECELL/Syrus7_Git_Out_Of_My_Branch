"""
File Overview: Celery tasks for advanced market data fetching and stream publishing.
Fetches option chain from internal NSE proxy API, persists to TimescaleDB, and publishes
to Redis Streams for PDE solver consumption.
Uses persistent event loop per worker thread (shared with ingestion_tasks).

All Functions/Classes:
- _fetch_and_publish_options_async: Core logic for chain retrieval and publishing.
    Data: symbol -> raw chain -> TimescaleDB + Redis Stream.
- fetch_and_publish_options: Celery task wrapper. Data: symbol -> async fetcher.

Endpoints/APIs: GET /v1/ingestion/options/{symbol} (Internal proxy, consumed by this task)

Database Tables: TimescaleDB (tickdata), Redis (Streams: stream:options.raw_fetched)
"""
import json
import logging
import asyncio
from celery import shared_task
from shared.infrastructure.redis_client import get_redis_client
from shared.constants import Streams

# Reuse persistent loop from ingestion_tasks
from domains.ingestion.tasks.ingestion_tasks import _get_or_create_loop

logger = logging.getLogger(__name__)


async def _fetch_and_publish_options_async(symbol: str):
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

        # Fetch dividend yield dynamically from the yfinance adapter
        price_info = await adapter.fetch_price(symbol)
        dividend_yield = price_info.get("dividend_yield", 0.0) if price_info else 0.0

        S0 = dtos[0].underlying_price
        timestamp = datetime.now()

        # Prepare DB and PDE payloads
        strikes_payload = []
        db_records = []

        # Calculate T using nearest expiry (simplistic approximation)
        T = 30 / 365.0
        nearest_expiry_str = dtos[0].expiry
        try:
            expiry_dt = datetime.strptime(nearest_expiry_str, "%Y-%m-%d")
            days_to_expiry = (expiry_dt - timestamp).days
            T = max(days_to_expiry, 1) / 365.0
        except Exception:
            logger.warning("Failed to parse expiry date: %s", nearest_expiry_str)

        for dto in dtos:
            expiry_date = None
            try:
                expiry_date = datetime.strptime(dto.expiry, "%Y-%m-%d").date()
            except Exception:
                pass

            # Prepare for TimescaleDB
            db_records.append((
                timestamp, symbol, "NSE", dto.option_type, dto.ltp, dto.oi, dto.volume, expiry_date, dto.strike, dto.iv, S0
            ))

            # If strike is near the money (+/- 10%), include in PDE solver payload
            if dto.strike and S0 * 0.9 <= dto.strike <= S0 * 1.1:
                strikes_payload.append({
                    "strike": dto.strike,
                    "type": dto.option_type,
                    "iv": dto.iv,
                    "ltp": dto.ltp
                })

        # 1. Bulk Insert into TimescaleDB
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

        # 2. Publish to Redis Stream for PDE Solver
        payload = {
            "spot_price": S0,
            "risk_free_rate": 0.065,
            "dividend_yield": dividend_yield,
            "time_to_maturity": T,
            "strikes_data": strikes_payload
        }

        await redis.xadd(Streams.OPTIONS_RAW_FETCHED, {
            "symbol": symbol,
            "data": json.dumps(payload)
        })
        logger.debug("Published raw options for %s: %d ticks saved to DB, %d strikes to stream.",
                     symbol, len(db_records), len(strikes_payload))

    except Exception as e:
        logger.error("Error fetching/publishing options for %s: %s", symbol, e, exc_info=True)
    finally:
        await adapter.close()


@shared_task(queue='ingestion', name='ingestion.fetch_and_publish_options')
def fetch_and_publish_options(symbol: str = "NIFTY"):
    """
    Pulls raw chain from NSE wrapper and drops it into Redis Streams.
    """
    loop = _get_or_create_loop()
    loop.run_until_complete(_fetch_and_publish_options_async(symbol))
