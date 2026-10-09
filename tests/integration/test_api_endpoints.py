"""
Integration tests for FastAPI endpoints.

Migrated from: scripts/test_dynamic_pricer.py, scripts/verify_proxy.py
Uses FastAPI TestClient with mocked third-party integrations for reliable, offline-safe endpoint validation.
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock


@pytest.mark.integration
class TestPricerEndpoint:
    """Tests for /v1/pricer/ticker/{symbol} endpoint."""

    def test_pricer_returns_200_for_known_symbol(self, test_client):
        response = test_client.get("/v1/pricer/ticker/TCS")
        assert response.status_code == 200
        data = response.json()
        assert data["symbol"] == "TCS.NS"
        assert "stock_price" in data

    def test_pricer_response_structure(self, test_client):
        response = test_client.get("/v1/pricer/ticker/NIFTY")
        assert response.status_code == 200
        data = response.json()
        assert data.get("symbol") == "NIFTY"


@pytest.mark.integration
class TestOptionsEndpoint:
    """Tests for /v1/ingestion/options/{symbol} endpoint."""

    @patch("domains.ingestion.api.nse_options_router_api.refresh_nse_cookies", new_callable=AsyncMock)
    @patch("domains.ingestion.api.nse_options_router_api.client")
    def test_options_endpoint_responds(self, mock_client, mock_refresh, test_client):
        # Setup mock HTTP response for NSE equities / indices API
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "records": {
                "timestamp": "30-May-2026 15:30:00",
                "underlyingValue": 24500.0,
                "data": [
                    {
                        "strikePrice": 24500,
                        "expiryDate": "29-May-2026",
                        "CE": {"lastPrice": 100.0, "openInterest": 1000, "totalTradedVolume": 500, "impliedVolatility": 12.5},
                        "PE": {"lastPrice": 90.0, "openInterest": 1200, "totalTradedVolume": 600, "impliedVolatility": 13.0}
                    }
                ]
            }
        }
        mock_client.get = AsyncMock(return_value=mock_response)

        response = test_client.get("/v1/ingestion/options/NIFTY")
        assert response.status_code == 200
        data = response.json()
        assert data["symbol"] == "NIFTY"
        assert data["underlying_value"] == 24500.0
        assert len(data["raw_chain"]) == 1

    @patch("domains.ingestion.api.nse_options_router_api.refresh_nse_cookies", new_callable=AsyncMock)
    @patch("domains.ingestion.api.nse_options_router_api.client")
    def test_options_response_structure(self, mock_client, mock_refresh, test_client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "records": {
                "timestamp": "30-May-2026 15:30:00",
                "underlyingValue": 24500.0,
                "data": []
            }
        }
        mock_client.get = AsyncMock(return_value=mock_response)

        response = test_client.get("/v1/ingestion/options/NIFTY")
        assert response.status_code == 200
        data = response.json()
        assert "symbol" in data
