"""
Unit tests for NseApiAdapter.

Migrated from: scripts/test_fetch.py, scripts/test_prices.py,
               scripts/test_final.py, scripts/test_nifty.py

Tests the pure/static methods of NseApiAdapter without hitting live APIs.
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone
import pandas as pd

from domains.ingestion.infrastructure.outbound.nse_api_adapter import (
    NseApiAdapter,
    _to_yfinance_symbol,
)


@pytest.mark.unit
class TestYfinanceSymbolMapping:
    """Tests for _to_yfinance_symbol() helper."""

    def test_index_mapping(self):
        assert _to_yfinance_symbol("NIFTY") == "^NSEI"
        assert _to_yfinance_symbol("BANKNIFTY") == "^NSEBANK"
        assert _to_yfinance_symbol("FINNIFTY") == "^CNXFIN"

    def test_index_case_insensitive(self):
        assert _to_yfinance_symbol("nifty") == "^NSEI"
        assert _to_yfinance_symbol("Nifty") == "^NSEI"

    def test_regular_stock(self):
        assert _to_yfinance_symbol("RELIANCE") == "RELIANCE.NS"
        assert _to_yfinance_symbol("TCS") == "TCS.NS"
        assert _to_yfinance_symbol("INFY") == "INFY.NS"

    def test_already_suffixed(self):
        assert _to_yfinance_symbol("RELIANCE.NS") == "RELIANCE.NS"
        assert _to_yfinance_symbol("RELIANCE.BO") == "RELIANCE.BO"

    def test_caret_symbol_passthrough(self):
        assert _to_yfinance_symbol("^NSEI") == "^NSEI"


@pytest.mark.unit
class TestParseNseDate:
    """Tests for NseApiAdapter._parse_nse_date() static method."""

    def test_valid_date(self):
        assert NseApiAdapter._parse_nse_date("29-May-2026") == "2026-05-29"
        assert NseApiAdapter._parse_nse_date("01-Jan-2026") == "2026-01-01"
        assert NseApiAdapter._parse_nse_date("15-Dec-2025") == "2025-12-15"

    def test_single_digit_day(self):
        assert NseApiAdapter._parse_nse_date("5-Jun-2026") == "2026-06-05"

    def test_invalid_date(self):
        assert NseApiAdapter._parse_nse_date("") is None
        assert NseApiAdapter._parse_nse_date("invalid") is None
        assert NseApiAdapter._parse_nse_date("2026-05-29") is None  # Wrong format

    def test_case_insensitive_month(self):
        assert NseApiAdapter._parse_nse_date("29-may-2026") == "2026-05-29"
        assert NseApiAdapter._parse_nse_date("29-MAY-2026") == "2026-05-29"


@pytest.mark.unit
class TestParseOptionChain:
    """Tests for NseApiAdapter._parse_option_chain() static method."""

    def test_parse_valid_chain(self, sample_option_chain_raw):
        result = NseApiAdapter._parse_option_chain("NIFTY", sample_option_chain_raw)

        assert result is not None
        assert result["symbol"] == "NIFTY"
        assert result["spot_price"] == 24500.0
        assert "2026-05-29" in result["chains"]

        chain = result["chains"]["2026-05-29"]
        assert len(chain) == 6  # 3 strikes × 2 types (CE + PE)

        # Verify structure of first tick
        first_tick = chain[0]
        assert "strike" in first_tick
        assert "type" in first_tick
        assert "last_price" in first_tick
        assert "oi" in first_tick
        assert "volume" in first_tick
        assert "iv" in first_tick

    def test_parse_empty_chain(self):
        empty_data = {"records": {"underlyingValue": 0, "expiryDates": [], "data": []}}
        result = NseApiAdapter._parse_option_chain("NIFTY", empty_data)

        assert result is not None
        assert result["chains"] == {}
        assert result["spot_price"] == 0.0

    def test_parse_filters_zero_price(self):
        data = {
            "records": {
                "underlyingValue": 24500.0,
                "expiryDates": ["29-May-2026"],
                "data": [
                    {
                        "strikePrice": 24500,
                        "expiryDate": "29-May-2026",
                        "CE": {"lastPrice": 0, "openInterest": 100, "totalTradedVolume": 50, "impliedVolatility": 10.0},
                        "PE": {"lastPrice": 50.0, "openInterest": 200, "totalTradedVolume": 80, "impliedVolatility": 12.0},
                    }
                ],
            }
        }
        result = NseApiAdapter._parse_option_chain("NIFTY", data)
        chain = result["chains"]["2026-05-29"]
        # Only PE should be included (CE has lastPrice=0)
        assert len(chain) == 1
        assert chain[0]["type"] == "PE"

    def test_parse_skips_missing_expiry(self):
        data = {
            "records": {
                "underlyingValue": 24500.0,
                "expiryDates": [],
                "data": [
                    {
                        "strikePrice": 24500,
                        # Missing expiryDate
                        "CE": {"lastPrice": 100.0, "openInterest": 100, "totalTradedVolume": 50, "impliedVolatility": 10.0},
                    }
                ],
            }
        }
        result = NseApiAdapter._parse_option_chain("NIFTY", data)
        assert result["chains"] == {}


@pytest.mark.unit
class TestFetchPriceSync:
    """Tests for NseApiAdapter._fetch_price_sync() with mocked yfinance."""

    @patch("domains.ingestion.infrastructure.outbound.nse_api_adapter.yf")
    def test_successful_fetch(self, mock_yf):
        mock_hist = pd.DataFrame({
            "close": [24400.0, 24500.0],
            "open": [24350.0, 24450.0],
            "high": [24550.0, 24600.0],
            "low": [24300.0, 24400.0],
            "volume": [100000, 120000],
        }, index=pd.to_datetime(["2026-05-28", "2026-05-29"]))

        mock_ticker = MagicMock()
        mock_ticker.history.return_value = mock_hist
        mock_ticker.info = {"currency": "INR", "dividendYield": 0.015}
        mock_yf.Ticker.return_value = mock_ticker

        result = NseApiAdapter._fetch_price_sync("^NSEI")

        assert result is not None
        assert result["last_price"] == 24500.0
        assert result["previous_close"] == 24400.0
        assert result["open"] == 24450.0
        assert result["high"] == 24600.0
        assert result["low"] == 24400.0
        assert result["volume"] == 120000
        assert result["currency"] == "INR"
        assert result["dividend_yield"] == 0.015
        assert abs(result["change_percent"] - 0.41) < 0.01

    @patch("domains.ingestion.infrastructure.outbound.nse_api_adapter.yf")
    def test_empty_history_returns_none(self, mock_yf):
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame()
        mock_yf.Ticker.return_value = mock_ticker

        result = NseApiAdapter._fetch_price_sync("INVALID")
        assert result is None

    @patch("domains.ingestion.infrastructure.outbound.nse_api_adapter.yf")
    def test_exception_returns_none(self, mock_yf):
        mock_yf.Ticker.side_effect = Exception("Network error")

        result = NseApiAdapter._fetch_price_sync("^NSEI")
        assert result is None
