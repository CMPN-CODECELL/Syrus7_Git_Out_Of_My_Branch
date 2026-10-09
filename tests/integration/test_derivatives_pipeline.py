import asyncio
import os
import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import redis.asyncio as aioredis

from domains.ingestion.tasks.market_tasks import _fetch_and_publish_options_async
from domains.analytics.infrastructure.options_subscriber import OptionsPricingSubscriber
from shared.constants import RedisKeys, Streams


@pytest.mark.integration
async def test_derivatives_pipeline_e2e():
    """
    Automated end-to-end integration test for the Derivatives Ingestion and Pricing pipeline.
    """
    symbols = ["NIFTY", "RELIANCE"]
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    redis_client = aioredis.from_url(redis_url, decode_responses=True)
    try:
        await redis_client.ping()
    except Exception:
        await redis_client.aclose()
        pytest.skip("Redis server is not running")

    # Clean up keys first
    for sym in symbols:
        await redis_client.delete(
            RedisKeys.MARKET_OPTIONS.format(symbol=sym),
            RedisKeys.MARKET_OPTIONS_PRICED.format(symbol=sym)
        )

    # 1. Mock DB pool to prevent TimescaleDB connection issues
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    # 2. Mock outbound adapters to prevent real NSE WAF blocks and yfinance network requests
    # Prepare realistic options mock data
    mock_ticks = [
        MagicMock(
            underlying_price=24500.0,
            expiry="2026-06-05",
            strike=24500.0,
            option_type="CE",
            oi=80000,
            volume=20000,
            ltp=100.0,
            iv=0.138
        ),
        MagicMock(
            underlying_price=24500.0,
            expiry="2026-06-05",
            strike=24500.0,
            option_type="PE",
            oi=75000,
            volume=18000,
            ltp=110.0,
            iv=0.140
        )
    ]

    with patch("shared.infrastructure.database.get_database_pool", return_value=mock_pool), \
         patch("domains.ingestion.infrastructure.outbound.nse_api_adapter.NseApiAdapter.fetch_option_chain", return_value=mock_ticks), \
         patch("domains.ingestion.infrastructure.outbound.nse_api_adapter.NseApiAdapter.fetch_price", return_value={"dividend_yield": 0.012}):

        print("\n[1/3] Triggering option ingestion & DB persistence...")
        for sym in symbols:
            # Recompute and publish options raw data
            await _fetch_and_publish_options_async(sym)

        print("\n[2/3] Processing events from Redis Stream synchronously...")
        # Read from OPTIONS_RAW_FETCHED stream and process via OptionsPricingSubscriber
        subscriber = OptionsPricingSubscriber(redis_client)
        
        # Read all stream messages published during ingestion
        events = await redis_client.xread({Streams.OPTIONS_RAW_FETCHED: "0-0"}, count=10)
        assert len(events) > 0, "No raw options events published to Redis stream"

        for stream, messages in events:
            for message_id, payload in messages:
                # payload in redis-py with decode_responses=True is dict of string->string
                # Convert string payload back to bytes so subscriber can decode
                bytes_payload = {
                    k.encode(): v.encode() if isinstance(v, str) else v
                    for k, v in payload.items()
                }
                await subscriber.process_event(bytes_payload)

        print("\n[3/3] Verifying computed fair priced options in Redis...")
        for sym in symbols:
            priced_key = RedisKeys.MARKET_OPTIONS_PRICED.format(symbol=sym)
            cached_data_str = await redis_client.get(priced_key)
            assert cached_data_str is not None, f"Fair priced chain missing in Redis for {sym}"

            cached_data = json.loads(cached_data_str)
            assert cached_data["symbol"] == sym
            assert len(cached_data["chain"]) > 0

            priced_strike = cached_data["chain"][0]
            assert priced_strike["strike"] == 24500.0
            assert "fair_call" in priced_strike
            assert "fair_put" in priced_strike
            assert "bs_fair_call" in priced_strike
            assert "bs_fair_put" in priced_strike

            print(f"  ✅ {sym} Fair Call: {priced_strike['fair_call']:.2f} | Fair Put: {priced_strike['fair_put']:.2f}")

    # Cleanup Redis
    for sym in symbols:
        await redis_client.delete(
            RedisKeys.MARKET_OPTIONS.format(symbol=sym),
            RedisKeys.MARKET_OPTIONS_PRICED.format(symbol=sym),
            Streams.OPTIONS_RAW_FETCHED
        )
    await redis_client.aclose()
