"""
Unit tests for Historical OHLC domain entities, TimescaleDB repository, and Technical Indicators Engine.
"""
import pytest
from datetime import datetime, timezone
from domains.historical.domain.entities import CandleEntity
from domains.analytics.domain.services.technical_indicators_engine import TechnicalIndicatorsEngine


def test_candle_entity_creation():
    candle = CandleEntity(
        symbol="NIFTY",
        timestamp=datetime.now(timezone.utc),
        open=24500.0,
        high=24550.0,
        low=24480.0,
        close=24520.0,
        volume=15000,
        timeframe="1m"
    )
    assert candle.symbol == "NIFTY"
    assert candle.close == 24520.0


def test_technical_indicators_engine_rsi():
    # 20 incremental prices
    prices = [100.0 + i * 0.5 for i in range(20)]
    rsi = TechnicalIndicatorsEngine.calculate_rsi(prices, period=14)
    assert rsi is not None
    assert rsi > 70.0  # Strong uptrend RSI


def test_technical_indicators_engine_bollinger():
    prices = [100.0, 102.0, 101.0, 103.0, 102.5, 104.0, 103.5, 105.0] * 3
    bb = TechnicalIndicatorsEngine.calculate_bollinger_bands(prices, period=20)
    assert bb["middle"] is not None
    assert bb["upper"] > bb["middle"]
    assert bb["lower"] < bb["middle"]


def test_technical_indicators_engine_all():
    candles = [
        CandleEntity(
            symbol="TCS",
            timestamp=datetime.now(timezone.utc),
            open=3500.0 + i,
            high=3510.0 + i,
            low=3490.0 + i,
            close=3505.0 + i,
            volume=500,
            timeframe="1m"
        )
        for i in range(35)
    ]

    indicators = TechnicalIndicatorsEngine.compute_all_indicators(candles)
    assert indicators["rsi"] is not None
    assert indicators["macd"]["macd"] is not None
    assert indicators["bollinger"]["middle"] is not None
    assert indicators["candle_count"] == 35
