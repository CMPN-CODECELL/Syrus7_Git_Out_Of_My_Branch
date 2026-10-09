"""
Unit tests for domains/analytics domain services, value objects, and application services.
Hexagonal architecture validation.
"""
import pytest
from domains.analytics.domain.services.bsm_calculator import BsmCalculatorDomainService
from domains.analytics.domain.value_objects import GreekValueObject, PCRValueObject
from domains.analytics.application.services.greeks_pricing_service import GreeksPricingService


def test_bsm_calculator_call_price():
    # Standard ITM European Call: S0=100, K=100, T=1.0, r=5%, vol=20%
    price = BsmCalculatorDomainService.calculate_price(
        spot=100.0,
        strike=100.0,
        expiry_years=1.0,
        rate=0.05,
        volatility=0.20,
        option_type="call"
    )
    assert price > 9.0 and price < 11.0  # Approx ~10.45


def test_bsm_calculator_greeks():
    greeks = BsmCalculatorDomainService.calculate_greeks(
        spot=100.0,
        strike=100.0,
        expiry_years=1.0,
        rate=0.05,
        volatility=0.20,
        option_type="call"
    )
    assert isinstance(greeks, GreekValueObject)
    assert greeks.delta > 0.5 and greeks.delta < 0.7
    assert greeks.gamma > 0.0
    assert greeks.vega > 0.0


def test_bsm_calculator_implied_volatility_solver():
    target_price = 10.45
    iv = BsmCalculatorDomainService.solve_implied_volatility(
        market_price=target_price,
        spot=100.0,
        strike=100.0,
        expiry_years=1.0,
        rate=0.05,
        option_type="call"
    )
    assert abs(iv - 0.20) < 0.05


def test_pcr_value_object():
    pcr_bullish = PCRValueObject(value=1.5)
    assert pcr_bullish.interpretation() == "BULLISH"

    pcr_bearish = PCRValueObject(value=0.5)
    assert pcr_bearish.interpretation() == "BEARISH"


@pytest.mark.asyncio
async def test_greeks_pricing_service_single_option():
    service = GreeksPricingService()
    res = await service.calculate_single_option(
        spot=100.0,
        strike=100.0,
        expiry_days=30,
        rate=6.5,
        volatility=25.0,
        option_type="call"
    )
    assert "price" in res
    assert "delta" in res
    assert "gamma" in res
    assert "theta" in res
    assert "vega" in res
    assert "rho" in res


def test_technical_indicators_engine_macd_recurrence():
    from domains.analytics.domain.services.technical_indicators_engine import TechnicalIndicatorsEngine
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
    from domains.analytics.domain.services.technical_indicators_engine import TechnicalIndicatorsEngine
    highs = [105.0 + i for i in range(25)]
    lows = [95.0 + i for i in range(25)]
    closes = [100.0 + i for i in range(25)]
    atr = TechnicalIndicatorsEngine.calculate_atr(highs, lows, closes, period=14)
    assert atr is not None
    assert atr > 0.0
    assert abs(atr - 10.0) < 1.0  # Daily range is ~10.0

