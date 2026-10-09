"""
Unit tests for SymbolValidator.

Migrated from: scripts/test_symbols.py
Tests validate() and get_clean_symbol using local map and mocked yfinance.
"""

import pytest
from unittest.mock import patch, MagicMock
from shared.utils.symbol_validator import SymbolValidator


@pytest.mark.unit
class TestSymbolValidatorLocalMap:
    """Tests that use only the local NSE map (no external calls)."""

    def test_validate_index_symbols(self):
        assert SymbolValidator.validate("NIFTY") is True
        assert SymbolValidator.validate("BANKNIFTY") is True
        assert SymbolValidator.validate("FINNIFTY") is True

    def test_validate_local_map_stocks(self):
        for symbol in ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN"]:
            assert SymbolValidator.validate(symbol) is True, f"{symbol} should be valid"

    def test_validate_empty_and_none(self):
        assert SymbolValidator.validate("") is False
        assert SymbolValidator.validate(None) is False

    def test_validate_caret_symbols(self):
        assert SymbolValidator.validate("^NSEI") is True
        assert SymbolValidator.validate("^NSEBANK") is True

    def test_validate_case_insensitive(self):
        assert SymbolValidator.validate("nifty") is True
        assert SymbolValidator.validate("Reliance") is True
        assert SymbolValidator.validate("tcs") is True

    def test_get_clean_symbol_index(self):
        assert SymbolValidator.get_clean_symbol("NIFTY") == "NIFTY"
        assert SymbolValidator.get_clean_symbol("BANKNIFTY") == "BANKNIFTY"

    def test_get_clean_symbol_local_map(self):
        assert SymbolValidator.get_clean_symbol("RELIANCE") == "RELIANCE.NS"
        assert SymbolValidator.get_clean_symbol("TCS") == "TCS.NS"
        assert SymbolValidator.get_clean_symbol("INFY") == "INFY.NS"

    def test_get_clean_symbol_already_suffixed(self):
        assert SymbolValidator.get_clean_symbol("RELIANCE.NS") == "RELIANCE.NS"
        assert SymbolValidator.get_clean_symbol("RELIANCE.BO") == "RELIANCE.BO"

    def test_get_clean_symbol_empty(self):
        assert SymbolValidator.get_clean_symbol("") == ""
        assert SymbolValidator.get_clean_symbol(None) == ""

    def test_get_clean_symbol_case_insensitive(self):
        assert SymbolValidator.get_clean_symbol("reliance") == "RELIANCE.NS"
        assert SymbolValidator.get_clean_symbol("tcs") == "TCS.NS"

    def test_get_clean_symbol_with_whitespace(self):
        assert SymbolValidator.get_clean_symbol("  RELIANCE  ") == "RELIANCE.NS"


@pytest.mark.unit
class TestSymbolValidatorWithMockedYfinance:
    """Tests that mock yfinance to avoid hitting external APIs."""

    @patch("shared.utils.symbol_validator.yf")
    def test_validate_unknown_symbol_with_ns_suffix(self, mock_yf):
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = MagicMock(empty=False)
        mock_yf.Ticker.return_value = mock_ticker

        assert SymbolValidator.validate("UNKNOWNXYZ.NS") is True
        mock_yf.Ticker.assert_called_with("UNKNOWNXYZ.NS")

    @patch("shared.utils.symbol_validator.yf")
    def test_validate_unknown_symbol_not_found(self, mock_yf):
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = MagicMock(empty=True)
        mock_yf.Ticker.return_value = mock_ticker

        assert SymbolValidator.validate("FAKESYMBOL.NS") is False

    @patch("shared.utils.symbol_validator.yf")
    def test_get_clean_symbol_fallback_to_yfinance(self, mock_yf):
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = MagicMock(empty=False)
        mock_yf.Ticker.return_value = mock_ticker

        # Symbol not in local map, not in instruments catalog
        result = SymbolValidator.get_clean_symbol("UNKNOWNXYZ")
        assert result == "UNKNOWNXYZ.NS"
