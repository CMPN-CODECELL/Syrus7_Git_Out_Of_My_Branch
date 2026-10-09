"""
Unit tests for _get_market_status().

Tests the market hours logic for NSE India (9:15 AM - 3:30 PM IST, Mon-Fri).
"""

import pytest
from datetime import datetime
import pytz

from domains.ingestion.infrastructure.outbound.nse_api_adapter import _get_market_status
from shared.constants import MarketStatus

IST = pytz.timezone("Asia/Kolkata")


def _make_ist_datetime(year, month, day, hour, minute):
    """Helper to create timezone-aware IST datetime."""
    return IST.localize(datetime(year, month, day, hour, minute, 0))


@pytest.mark.unit
class TestGetMarketStatus:

    def test_market_open_during_hours(self):
        # Wednesday 11:00 AM IST
        dt = _make_ist_datetime(2026, 5, 27, 11, 0)
        result = _get_market_status(dt)
        assert result == MarketStatus.OPEN

    def test_market_open_at_start(self):
        # Wednesday 9:15 AM IST (market opens)
        dt = _make_ist_datetime(2026, 5, 27, 9, 15)
        result = _get_market_status(dt)
        assert result == MarketStatus.OPEN

    def test_pre_market(self):
        # Wednesday 8:00 AM IST
        dt = _make_ist_datetime(2026, 5, 27, 8, 0)
        result = _get_market_status(dt)
        assert result == MarketStatus.PRE_MARKET

    def test_post_market(self):
        # Wednesday 4:00 PM IST
        dt = _make_ist_datetime(2026, 5, 27, 16, 0)
        result = _get_market_status(dt)
        assert result == MarketStatus.POST_MARKET

    def test_weekend_saturday(self):
        # Saturday 11:00 AM IST
        dt = _make_ist_datetime(2026, 5, 30, 11, 0)
        result = _get_market_status(dt)
        assert result == MarketStatus.CLOSED

    def test_weekend_sunday(self):
        # Sunday 11:00 AM IST
        dt = _make_ist_datetime(2026, 5, 31, 11, 0)
        result = _get_market_status(dt)
        assert result == MarketStatus.CLOSED
