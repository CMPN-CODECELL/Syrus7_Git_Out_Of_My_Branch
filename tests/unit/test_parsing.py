from datetime import date

import pytest

from domains.copilot.domain.parsing import ParseError, parse_price_paise, resolve_expiry, round_to_tick


@pytest.mark.parametrize("text,paise", [
    ("₹2,800.50", 280050),
    ("2800.03", 280003),
    ("2.8k", 280000),
    ("Rs 1,40,000", 14000000),
    ("rs.1400", 140000),
    ("1400", 140000),
    ("0.05", 5),
    ("1.5 lakh", 15000000),
])
def test_prices_parse_to_exact_paise(text, paise):
    assert parse_price_paise(text) == paise


@pytest.mark.parametrize("text", ["-5", "0", "abc", "2800.035", "", "12..5", "1e9"])
def test_bad_prices_refused(text):
    with pytest.raises(ParseError):
        parse_price_paise(text)


def test_tick_rounding_favours_the_trader():
    assert round_to_tick(280003, 5, "BUY") == 280000
    assert round_to_tick(280003, 5, "SELL") == 280005
    assert round_to_tick(280005, 5, "BUY") == 280005
    with pytest.raises(ParseError):
        round_to_tick(3, 5, "BUY")


def test_expiry_phrases():
    today = date(2026, 10, 9)
    listed = [date(2026, 10, 7), date(2026, 10, 14), date(2026, 10, 21), date(2026, 10, 28), date(2026, 11, 25)]
    assert resolve_expiry(None, listed, today) == date(2026, 10, 14)  # expired 7 Oct skipped
    assert resolve_expiry("next", listed, today) == date(2026, 10, 21)
    assert resolve_expiry("28 Oct", listed, today) == date(2026, 10, 28)
    assert resolve_expiry("oct", listed, today) == date(2026, 10, 28)
    assert resolve_expiry("2026-11-25", listed, today) == date(2026, 11, 25)
    with pytest.raises(ParseError):
        resolve_expiry("7 Oct", listed, today)
    with pytest.raises(ParseError):
        resolve_expiry("someday", listed, today)
