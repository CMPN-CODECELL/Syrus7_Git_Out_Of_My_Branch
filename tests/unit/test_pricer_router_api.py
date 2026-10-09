"""
Unit tests for domains/analytics/api/pricer_router_api.py.

Tests GET /v1/pricer/ticker/{symbol} and POST /v1/pricer/calculate
covering Redis caching, dynamic market fetch fallback, fail-fast 503 handling,
and BSM pricing computation logic.
"""

import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


@pytest.mark.unit
class TestPricerTickerEndpoint:
    """Unit tests for get_ticker_parameters endpoint."""

    @patch("domains.analytics.api.pricer_router_api.get_redis_client")
    def test_get_ticker_parameters_from_redis_cache(self, mock_get_redis, test_client):
        """Should return cached option chain and params directly from Redis if available."""
        mock_redis = AsyncMock()
        mock_get_redis.return_value = mock_redis

        cached_data = {
            "symbol": "NIFTY",
            "spot_price": 24500.0,
            "expiry_dates": ["2026-06-05"],
            "chains": {
                "2026-06-05": [
                    {
                        "strike": 24500.0,
                        "type": "CE",
                        "last_price": 120.0,
                        "oi": 5000,
                        "volume": 1200,
                        "iv": 0.15,
                        "expiry": "2026-06-05"
                    },
                    {
                        "strike": 24500.0,
                        "type": "PE",
                        "last_price": 110.0,
                        "oi": 4500,
                        "volume": 1000,
                        "iv": 0.16,
                        "expiry": "2026-06-05"
                    }
                ]
            },
            "fetched_at": "2026-05-29T10:00:00Z",
            "summary": {"total_strikes": 1}
        }
        mock_redis.get.side_effect = lambda key: json.dumps(cached_data) if "options" in key else json.dumps({"last_price": 24500.0})

        response = test_client.get("/v1/pricer/ticker/NIFTY")
        assert response.status_code == 200
        data = response.json()
        assert data["symbol"] == "NIFTY"
        assert data["stock_price"] == 24500.0
        assert data["source"] == "redis_cache"
        assert "2026-06-05" in data["option_chains"]
        assert len(data["option_chains"]["2026-06-05"]) == 1

    @patch("domains.analytics.api.pricer_router_api.get_redis_client")
    @patch("domains.ingestion.infrastructure.outbound.adapter_factory.get_market_data_adapter")
    def test_get_ticker_parameters_live_fetch_fallback(self, mock_get_adapter, mock_get_redis, test_client):
        """Should fall back to live market adapter when Redis cache is empty."""
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        mock_get_redis.return_value = mock_redis

        mock_dto = MagicMock(
            underlying_price=3500.0,
            expiry="2026-06-25",
            strike=3500.0,
            option_type="CE",
            oi=2000,
            volume=500,
            ltp=85.0,
            iv=0.20,
            bid=None,
            bid_qty=None,
            ask=None,
            ask_qty=None
        )
        mock_adapter = AsyncMock()
        mock_adapter.fetch_option_chain.return_value = [mock_dto]
        mock_adapter.fetch_price.return_value = {"last_price": 3500.0}
        mock_get_adapter.return_value = mock_adapter

        response = test_client.get("/v1/pricer/ticker/TCS")
        assert response.status_code == 200
        data = response.json()
        assert data["symbol"] == "TCS.NS"
        assert data["stock_price"] == 3500.0
        assert data["source"] == "redis_cache"
        assert "2026-06-25" in data["option_chains"]

    @patch("domains.analytics.api.pricer_router_api.get_redis_client")
    @patch("domains.ingestion.infrastructure.outbound.adapter_factory.get_market_data_adapter")
    def test_get_ticker_parameters_unavailable_returns_503(self, mock_get_adapter, mock_get_redis, test_client):
        """Should return explicit 503 status when all market data sources fail."""
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        mock_get_redis.return_value = mock_redis

        mock_adapter = AsyncMock()
        mock_adapter.fetch_option_chain.return_value = []
        mock_adapter.fetch_price.return_value = None
        mock_get_adapter.return_value = mock_adapter

        response = test_client.get("/v1/pricer/ticker/RELIANCE")
        assert response.status_code == 503
        assert "Live market data is currently unavailable" in response.json()["detail"]

    def test_get_ticker_parameters_invalid_symbol_format(self, test_client):
        """Should return 400 Bad Request for symbols with invalid non-alphanumeric chars."""
        response = test_client.get("/v1/pricer/ticker/$$$INVALID!!!")
        assert response.status_code == 400
        assert "invalid or not supported" in response.json()["detail"]


@pytest.mark.unit
class TestPricerCalculateEndpoint:
    """Unit tests for calculate_bsm endpoint."""

    def test_calculate_call_option_success(self, test_client):
        payload = {
            "S0": 100.0,
            "K": 100.0,
            "T_days": 30,
            "r": 5.0,
            "sigma": 20.0,
            "option_type": "call",
            "q": 0.0,
            "market_mid": 2.20
        }
        response = test_client.post("/v1/pricer/calculate", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["S0"] == 100.0
        assert data["K"] == 100.0
        assert data["option_type"] == "call"
        assert data["fair_value"] > 0.0
        assert data["d1"] is not None
        assert data["d2"] is not None
        assert data["edge"] is not None

    def test_calculate_put_option_success(self, test_client):
        payload = {
            "S0": 100.0,
            "K": 100.0,
            "T_days": 30,
            "r": 5.0,
            "sigma": 20.0,
            "option_type": "put",
            "q": 0.0
        }
        response = test_client.post("/v1/pricer/calculate", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["option_type"] == "put"
        assert data["fair_value"] > 0.0

    def test_calculate_invalid_positive_inputs_returns_422(self, test_client):
        payload = {
            "S0": 0.0,
            "K": 100.0,
            "T_days": 30,
            "r": 5.0,
            "sigma": 20.0,
            "option_type": "call"
        }
        response = test_client.post("/v1/pricer/calculate", json=payload)
        assert response.status_code == 422

    def test_calculate_invalid_option_type_returns_400(self, test_client):
        payload = {
            "S0": 100.0,
            "K": 100.0,
            "T_days": 30,
            "r": 5.0,
            "sigma": 20.0,
            "option_type": "straddle"
        }
        response = test_client.post("/v1/pricer/calculate", json=payload)
        assert response.status_code == 400
        assert "Option type must be 'call' or 'put'" in response.json()["detail"]
