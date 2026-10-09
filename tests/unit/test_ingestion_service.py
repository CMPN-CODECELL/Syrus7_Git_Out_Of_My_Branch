import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from domains.ingestion.application.services.ingestion_service import IngestionService
from domains.ingestion.application.dto.raw_tick_dto import RawTickDTO
from datetime import datetime, timezone
from shared.constants import Channels

@pytest.mark.unit
async def test_ingest_market_data_publishes_pubsub():
    mock_price = AsyncMock()
    mock_option = AsyncMock()
    mock_dedup = AsyncMock()
    mock_bus = AsyncMock()
    mock_redis = AsyncMock()
    
    svc = IngestionService(mock_price, mock_option, mock_dedup, mock_bus, mock_redis)
    
    # Mock return value of fetch_price
    mock_price.fetch_price.return_value = {
        "last_price": 22450.00,
        "open": 22400.0,
        "high": 22500.0,
        "low": 22350.0,
        "volume": 100000,
        "previous_close": 22400.0,
        "change_percent": 0.22,
        "currency": "INR",
        "last_updated": "2026-06-02"
    }
    
    await svc.ingest_market_data("NIFTY")
    
    # Verify redis cache set
    mock_redis.set.assert_called_once()
    
    # Verify pub/sub publish called with Channels.PRICE_UPDATED
    mock_redis.publish.assert_called_once()
    pub_channel = mock_redis.publish.call_args[0][0]
    pub_data = json.loads(mock_redis.publish.call_args[0][1])
    
    assert pub_channel == Channels.PRICE_UPDATED.format(symbol="NIFTY")
    assert pub_data["last_price"] == 22450.00


@pytest.mark.unit
async def test_ingest_options_publishes_pubsub():
    mock_price = AsyncMock()
    mock_option = AsyncMock()
    mock_dedup = AsyncMock()
    mock_bus = MagicMock()  # Changed to MagicMock since not used directly
    mock_redis = AsyncMock()
    
    svc = IngestionService(mock_price, mock_option, mock_dedup, mock_bus, mock_redis)
    
    # Mock return value of fetch_option_chain
    mock_option.fetch_option_chain.return_value = [
        RawTickDTO(
            symbol="NIFTY",
            expiry="2026-06-04",
            strike=22400.0,
            option_type="CE",
            oi=1000,
            volume=500,
            ltp=120.0,
            iv=0.12,
            underlying_price=22450.0,
            timestamp=datetime.now(timezone.utc)
        )
    ]
    
    await svc.ingest_options("NIFTY")
    
    # Verify redis cache set
    mock_redis.set.assert_called_once()
    
    # Verify pub/sub publish called with Channels.OPTIONS_UPDATED
    mock_redis.publish.assert_called_once()
    pub_channel = mock_redis.publish.call_args[0][0]
    pub_data = json.loads(mock_redis.publish.call_args[0][1])
    
    assert pub_channel == Channels.OPTIONS_UPDATED.format(symbol="NIFTY")
    assert pub_data["symbol"] == "NIFTY"
    assert pub_data["status"] == "updated"
