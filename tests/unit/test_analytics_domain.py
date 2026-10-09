"""
Unit tests for domains/analytics domain services and value objects.
"""
from domains.analytics.domain.value_objects import PCRValueObject
from domains.analytics.domain.services.technical_indicators_engine import TechnicalIndicatorsEngine


def test_pcr_value_object():
    pcr_bullish = PCRValueObject(value=1.5)
    assert pcr_bullish.interpretation() == "BULLISH"

    pcr_bearish = PCRValueObject(value=0.5)
    assert pcr_bearish.interpretation() == "BEARISH"


def test_technical_indicators_engine_macd_recurrence():
    # 50 constant prices -> MACD, signal, histogram must converge to 0
    constant_prices = [100.0] * 50
    macd_res = TechnicalIndicatorsEngine.calculate_macd(constant_prices)
    assert macd_res["macd"] is not None
    assert abs(macd_res["macd"]) < 1e-3
    assert abs(macd_res["signal"]) < 1e-3
    assert abs(macd_res["histogram"]) < 1e-3

    # Upward trending series
    trending_prices = [100.0 + i * 1.5 for i in range(50)]
    trending_macd = TechnicalIndicatorsEngine.calculate_macd(trending_prices)
    assert trending_macd["macd"] > 0.0
    assert trending_macd["signal"] > 0.0


def test_technical_indicators_engine_atr():
    highs = [105.0 + i for i in range(25)]
    lows = [95.0 + i for i in range(25)]
    closes = [100.0 + i for i in range(25)]
    atr = TechnicalIndicatorsEngine.calculate_atr(highs, lows, closes, period=14)
    assert atr is not None
    assert atr > 0.0
    assert abs(atr - 10.0) < 1.0  # Daily range is ~10.0


def test_rsi_refuses_short_series():
    # RSI(14) needs 15 closes; with 14 it must return None rather than a made-up value.
    assert TechnicalIndicatorsEngine.calculate_rsi([100.0 + i for i in range(14)]) is None
    assert TechnicalIndicatorsEngine.calculate_rsi([100.0 + i for i in range(15)]) == 100.0
