from domains.copilot.domain import portfolio_math as pm


def test_position_pnl_uses_guide_formula_in_paise():
    row = pm.position_pnl({"netQuantity": 10, "netPrice": 140000, "token": 2885, "product": "INTRADAY"}, 141000, 0, "RELIANCE", False)
    assert row.unrealized == 10_000  # (1410 - 1400) x 10 = Rs 100.00
    assert row.move_pct == 0.71


def test_short_position_rise_counts_as_down():
    assert pm.move_pct(10000, 10600, -5) == -6.0
    assert pm.move_pct(10000, 9400, -5) == 6.0


def test_closed_position_has_zero_unrealized():
    row = pm.position_pnl({"netQuantity": 0, "netPrice": 0}, None, 500, "X", True)
    assert row.unrealized == 0 and row.realized_today == 500 and row.move_pct is None


def test_realized_from_todays_trades():
    trades = [
        {"token": 1, "product": "INTRADAY", "quantity": 10, "price": 10000},
        {"token": 1, "product": "INTRADAY", "quantity": -6, "price": 10500},
        {"token": 1, "product": "CNC", "quantity": -3, "price": 99999},  # different product: no match
    ]
    assert pm.realized_by_key(trades) == {(1, "INTRADAY"): 3000}  # 6 x Rs 5


def test_holding_pnl_and_day_change():
    row = pm.holding_pnl({"symbol": "INFY", "freeQty": 8, "btstQty": 2, "price": 150000, "prevClose": 152000}, 153000, False)
    assert row.qty == 10 and row.pnl == 30_000 and row.day_change == 10_000


def test_rupee_formatting_indian_grouping():
    assert pm.rupees(123456789) == "Rs 12,34,567.89"
    assert pm.rupees(-5) == "-Rs 0.05"
    assert pm.rupees(None) is None
