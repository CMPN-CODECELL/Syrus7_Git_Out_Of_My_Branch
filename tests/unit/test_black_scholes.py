import pytest
from domains.analytics.application.services.derivatives.black_scholes import BlackScholesMerton


@pytest.mark.unit
def test_black_scholes_call():
    # S=100, K=100, T=1, r=0.05, sigma=0.2, q=0.0
    # Expected call price is ~10.450585
    pricer = BlackScholesMerton(S0=100.0, K=100.0, T=1.0, r=0.05, sigma=0.2, option_type='call')
    price = pricer.solve()
    assert price == pytest.approx(10.450585, abs=1e-4)


@pytest.mark.unit
def test_black_scholes_put():
    # S=100, K=100, T=1, r=0.05, sigma=0.2, q=0.0
    # Expected put price is ~5.573526
    pricer = BlackScholesMerton(S0=100.0, K=100.0, T=1.0, r=0.05, sigma=0.2, option_type='put')
    price = pricer.solve()
    assert price == pytest.approx(5.573526, abs=1e-4)


@pytest.mark.unit
def test_black_scholes_with_dividends():
    # S=100, K=95, T=0.5, r=0.08, sigma=0.3, q=0.03
    # Expected call price is ~12.144378
    pricer = BlackScholesMerton(S0=100.0, K=95.0, T=0.5, r=0.08, sigma=0.3, option_type='call', q=0.03)
    price = pricer.solve()
    assert price == pytest.approx(12.144378, abs=1e-4)
