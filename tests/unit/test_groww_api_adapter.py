"""
Unit tests for GrowwApiAdapter.
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone

from domains.ingestion.infrastructure.outbound.groww_api_adapter import GrowwApiAdapter
from domains.ingestion.application.dto.raw_tick_dto import RawTickDTO


@pytest.mark.unit
class TestGrowwApiAdapterToken:
    """Tests for token generation in GrowwApiAdapter."""

    @patch("domains.ingestion.infrastructure.outbound.groww_api_adapter.GROWW_SDK_AVAILABLE", True)
    @patch("domains.ingestion.infrastructure.outbound.groww_api_adapter.GrowwAPI", create=True)
    @pytest.mark.asyncio
    async def test_dynamic_token_retrieval(self, mock_sdk):
        mock_sdk.get_access_token.return_value = "mock_generated_token"

        adapter = GrowwApiAdapter(api_key="key", secret_key="secret")
        try:
            token = await adapter._get_token()

            assert token == "mock_generated_token"
            mock_sdk.get_access_token.assert_called_once_with(api_key="key", secret="secret")
        finally:
            await adapter.close()

    @pytest.mark.asyncio
    async def test_configured_token_precedence(self):
        adapter = GrowwApiAdapter(api_key="key", secret_key="secret", access_token="pre_set_token")
        try:
            token = await adapter._get_token()

            assert token == "pre_set_token"
        finally:
            await adapter.close()


@pytest.mark.unit
class TestGrowwApiAdapterFetchPrice:
    """Tests for fetch_price in GrowwApiAdapter."""

    @pytest.mark.asyncio
    @patch("domains.ingestion.infrastructure.outbound.groww_api_adapter.GrowwApiAdapter._get_token")
    async def test_fetch_price_success(self, mock_get_token):
        mock_get_token.return_value = "valid_token"

        # Mock aiohttp ClientSession
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json.return_value = {
            "status": "SUCCESS",
            "payload": {
                "last_price": 24500.0,
                "ohlc": {"open": 24450.0, "high": 24600.0, "low": 24400.0, "close": 24400.0},
                "volume": 120000,
                "day_change_perc": 0.41
            }
        }

        mock_session = MagicMock()
        mock_session.get.return_value.__aenter__.return_value = mock_response

        adapter = GrowwApiAdapter(access_token="valid_token")
        adapter._ensure_session = AsyncMock(return_value=mock_session)

        # Mock fallback fetch_price to not call real yfinance for dividend_yield
        adapter._fallback_adapter.fetch_price = AsyncMock(return_value={"dividend_yield": 0.015})

        try:
            result = await adapter.fetch_price("NIFTY")

            assert result is not None
            assert result["last_price"] == 24500.0
            assert result["open"] == 24450.0
            assert result["high"] == 24600.0
            assert result["low"] == 24400.0
            assert result["volume"] == 120000
            assert result["change_percent"] == 0.41
            assert result["dividend_yield"] == 0.015
        finally:
            await adapter.close()

    @pytest.mark.asyncio
    @patch("domains.ingestion.infrastructure.outbound.groww_api_adapter.GrowwApiAdapter._get_token")
    async def test_fetch_price_fallback(self, mock_get_token):
        mock_get_token.return_value = None  # No token -> fallback

        adapter = GrowwApiAdapter()
        adapter._fallback_adapter.fetch_price = AsyncMock(return_value={"last_price": 100.0})

        try:
            result = await adapter.fetch_price("RELIANCE")

            assert result is not None
            assert result["last_price"] == 100.0
            adapter._fallback_adapter.fetch_price.assert_called_once_with("RELIANCE")
        finally:
            await adapter.close()


@pytest.mark.unit
class TestGrowwApiAdapterFetchOptionChain:
    """Tests for fetch_option_chain in GrowwApiAdapter."""

    @pytest.mark.asyncio
    @patch("domains.ingestion.infrastructure.outbound.groww_api_adapter.GrowwApiAdapter._get_token")
    async def test_fetch_option_chain_success(self, mock_get_token):
        mock_get_token.return_value = "valid_token"

        # Mock aiohttp responses for expiries & option-chain
        mock_exp_resp = AsyncMock()
        mock_exp_resp.status = 200
        mock_exp_resp.json.return_value = ["2026-06-04", "2026-06-11"]

        mock_chain_resp = AsyncMock()
        mock_chain_resp.status = 200
        mock_chain_resp.json.return_value = {
            "status": "SUCCESS",
            "payload": {
                "underlying_ltp": 24480.0,
                "strikes": {
                    "24500": {
                        "CE": {"ltp": 120.0, "open_interest": 5000, "volume": 15000, "greeks": {"iv": 15.5}},
                        "PE": {"ltp": 90.0, "open_interest": 4000, "volume": 12000, "greeks": {"iv": 14.5}}
                    }
                }
            }
        }


        # Setup mock session to return expiries first, then chains
        mock_session = MagicMock()
        
        class MockGetContext:
            def __init__(self, url, *args, **kwargs):
                self.url = url
            async def __aenter__(self):
                if "expiries" in self.url:
                    return mock_exp_resp
                else:
                    return mock_chain_resp
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        mock_session.get.side_effect = lambda url, *args, **kwargs: MockGetContext(url, *args, **kwargs)

        adapter = GrowwApiAdapter(access_token="valid_token")
        adapter._ensure_session = AsyncMock(return_value=mock_session)
        adapter.fetch_price = AsyncMock(return_value={"last_price": 24480.0})
        adapter._fallback_adapter.fetch_expiry_dates = AsyncMock(return_value=["2026-06-04", "2026-06-11"])


        try:
            result = await adapter.fetch_option_chain("NIFTY")

            assert len(result) == 4 # 2 expiries * 2 types (CE/PE)
            assert isinstance(result[0], RawTickDTO)
            assert result[0].strike == 24500.0
            assert result[0].underlying_price == 24480.0
            
            # Verify CE normalization (15.5 -> 0.155)
            ce_tick = [r for r in result if r.option_type == "CE" and r.expiry == "2026-06-04"][0]
            assert ce_tick.ltp == 120.0
            assert ce_tick.oi == 5000
            assert ce_tick.volume == 15000
            assert abs(ce_tick.iv - 0.155) < 0.001
        finally:
            await adapter.close()

    @pytest.mark.asyncio
    @patch("domains.ingestion.infrastructure.outbound.groww_api_adapter.GrowwApiAdapter._get_token")
    async def test_fetch_option_chain_fallback(self, mock_get_token):
        mock_get_token.return_value = None  # No token -> fallback

        adapter = GrowwApiAdapter()
        adapter._fallback_adapter.fetch_option_chain = AsyncMock(return_value=[
            RawTickDTO(
                symbol="NIFTY", expiry="2026-06-04", strike=24500.0, option_type="CE",
                oi=10, volume=20, ltp=15.0, timestamp=datetime.now(timezone.utc)
            )
        ])

        try:
            result = await adapter.fetch_option_chain("NIFTY")

            assert len(result) == 1
            assert result[0].ltp == 15.0
            adapter._fallback_adapter.fetch_option_chain.assert_called_once_with("NIFTY")
        finally:
            await adapter.close()
