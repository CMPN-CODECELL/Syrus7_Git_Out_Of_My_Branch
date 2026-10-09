"""
Unit tests for VolatilitySurface domain service.
Validates cubic spline IV smile calibration and PDE fair value mispricing calculation.
"""

import pytest
from domains.analytics.domain.services.volatility_surface import VolatilitySurface


def test_volatility_surface_cubic_spline_fit():
    spot = 24000.0
    strikes = [23600.0, 23800.0, 24000.0, 24200.0, 24400.0]
    # Implied volatilities exhibiting standard volatility smile
    ivs = [0.165, 0.150, 0.138, 0.145, 0.160]

    surface = VolatilitySurface(strikes=strikes, ivs=ivs, spot=spot)
    assert surface.is_fitted is True
    assert surface.strike_count == 5

    # ATM IV check
    atm_iv = surface.get_atm_iv()
    assert abs(atm_iv - 0.138) < 1e-3

    # Interpolated in-between strike (23900)
    interp_iv = surface.get_surface_iv(23900.0)
    assert 0.138 < interp_iv < 0.150


def test_volatility_surface_percentage_iv_normalization():
    spot = 24000.0
    strikes = [23600.0, 23800.0, 24000.0, 24200.0]
    # User passes percentage numbers instead of decimal (e.g. 15.5%)
    ivs = [16.5, 15.0, 13.8, 14.5]

    surface = VolatilitySurface(strikes=strikes, ivs=ivs, spot=spot)
    assert surface.is_fitted is True
    assert surface.get_surface_iv(24000.0) < 1.0  # Normalized to decimal
    assert abs(surface.get_surface_iv(24000.0) - 0.138) < 1e-3


def test_volatility_surface_pde_mispricing():
    spot = 24000.0
    strike = 24000.0
    strikes = [23600.0, 23800.0, 24000.0, 24200.0, 24400.0]
    ivs = [0.165, 0.150, 0.140, 0.148, 0.160]

    surface = VolatilitySurface(strikes=strikes, ivs=ivs, spot=spot)
    pde_fair_val = surface.compute_pde_fair_value(
        strike=strike,
        spot=spot,
        expiry_years=7.0 / 365.0,
        rate=0.065,
        option_type="call",
        grid_m=100,
        grid_n=100,
    )
    assert pde_fair_val > 0.0

    # Market underpriced relative to PDE fair value -> negative delta
    market_price_undervalued = pde_fair_val - 25.0
    mispricing = surface.get_mispricing(
        strike=strike,
        market_price=market_price_undervalued,
        spot=spot,
        expiry_years=7.0 / 365.0,
        rate=0.065,
        option_type="call",
        grid_m=100,
        grid_n=100,
    )
    assert abs(mispricing - (-25.0)) < 0.1


def test_volatility_surface_sparse_strikes_fallback():
    spot = 24000.0
    # Only 2 strikes provided (below MIN_STRIKES_REQUIRED=4)
    strikes = [23800.0, 24000.0]
    ivs = [0.15, 0.14]

    surface = VolatilitySurface(strikes=strikes, ivs=ivs, spot=spot)
    assert surface.is_fitted is False
    assert abs(surface.get_surface_iv(24100.0) - 0.145) < 1e-3
