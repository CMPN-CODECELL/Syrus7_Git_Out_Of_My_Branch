import json
from unittest.mock import AsyncMock
import pytest

from domains.analytics.infrastructure.options_subscriber import OptionsPricingSubscriber
from shared.constants import Streams, Channels


@pytest.mark.unit
async def test_options_pricing_subscriber_process_event():
    mock_redis = AsyncMock()
    subscriber = OptionsPricingSubscriber(mock_redis)

    # Mock payload from Redis Stream
    payload = {
        b"symbol": b"RELIANCE",
        b"data": json.dumps({
            "spot_price": 2500.0,
            "risk_free_rate": 0.065,
            "dividend_yield": 0.012,
            "time_to_maturity": 0.08,  # ~30 days
            "strikes_data": [
                {"strike": 2500.0, "type": "CE", "iv": 0.18, "ltp": 45.0},
                {"strike": 2500.0, "type": "PE", "iv": 0.19, "ltp": 42.0}
            ]
        }).encode("utf-8")
    }

    # Run process_event
    await subscriber.process_event(payload)

    # Check that it set cache in Redis
    mock_redis.set.assert_called_once()
    cache_key = mock_redis.set.call_args[0][0]
    assert "market:options:priced:RELIANCE" in cache_key

    cache_value = json.loads(mock_redis.set.call_args[0][1])
    assert cache_value["symbol"] == "RELIANCE"
    assert len(cache_value["chain"]) == 1
    
    priced_strike = cache_value["chain"][0]
    assert priced_strike["strike"] == 2500.0
    assert "fair_call" in priced_strike
    assert "fair_put" in priced_strike
    assert "bs_fair_call" in priced_strike
    assert "bs_fair_put" in priced_strike
    assert priced_strike["live_call"] == 45.0
    assert priced_strike["live_put"] == 42.0

    # Verify BSM call/put fair values are correct and realistic
    assert priced_strike["bs_fair_call"] == pytest.approx(56.16, abs=0.1)
    assert priced_strike["bs_fair_put"] == pytest.approx(48.31, abs=0.1)

    # Check stream publishing
    mock_redis.xadd.assert_called_once()
    assert mock_redis.xadd.call_args[0][0] == Streams.OPTIONS_PRICED

    # Check pubsub publishing
    mock_redis.publish.assert_called_once()
    assert Channels.OPTIONS_UPDATED.format(symbol="RELIANCE") in mock_redis.publish.call_args[0][0]
