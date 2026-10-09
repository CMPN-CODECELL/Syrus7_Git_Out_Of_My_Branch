"""OrderBuilder: every validation rule from docs/PHASE2_PLAN.md."""
import pytest

from domains.copilot.application.order_builder import NeedsClarification, OrderRefused
from shared.contracts.orders import OrderChangeDraft, OrderDraft
from tests.fakes.orders_world import build_world


def D(**kw) -> OrderDraft:
    return OrderDraft(**kw)


async def test_market_buy_defaults_to_cnc_with_reference_price():
    w = build_world()
    built = await w.builder.build_place(D(action="BUY", symbol_query="reliance", quantity=10))
    assert built.payload.to_request_json() == {"exchange": "NSE", "token": 2885, "qty": 10, "price": 0, "book": "RL",
                                               "product": "CNC", "validity": "Day"}
    card = built.display
    assert (card.side, card.quantity, card.order_type, card.product) == ("BUY", 10, "MARKET", "CNC")
    assert card.reference_ltp_paise == 280000 and card.estimated_value_paise == 2_800_000
    assert built.reference_ltp == 280000 and card.amo is False


async def test_missing_quantity_is_asked_never_defaulted():
    w = build_world()
    with pytest.raises(NeedsClarification) as info:
        await w.builder.build_place(D(action="BUY", symbol_query="RELIANCE"))
    assert "How many" in info.value.message


async def test_ambiguous_symbol_asks():
    w = build_world()
    with pytest.raises(NeedsClarification) as info:
        await w.builder.build_place(D(action="BUY", symbol_query="HDFC", quantity=1))
    assert "HDFCBANK" in info.value.message


async def test_index_is_refused_with_alternative():
    w = build_world()
    with pytest.raises(OrderRefused) as info:
        await w.builder.build_place(D(action="BUY", symbol_query="NIFTY", quantity=1))
    assert "index" in info.value.message and "option" in info.value.message


async def test_limit_price_text_is_parsed_and_rounded_in_traders_favour():
    w = build_world()
    buy = await w.builder.build_place(D(action="BUY", symbol_query="RELIANCE", quantity=1, order_type="LIMIT", limit_price="₹2,800.05"))
    assert buy.payload.price == 280000 and any("rounded down" in n for n in buy.display.notices)
    sell_w = build_world()
    sell_w.fake.holdings = [{"isin": "INE002A01018", "symbol": "RELIANCE", "freeQty": 5, "btstQty": 0, "sellQty": 0, "price": 1, "prevClose": 1}]
    sell = await sell_w.builder.build_place(D(action="SELL", symbol_query="RELIANCE", quantity=1, limit_price="2.80005k"))
    assert sell.payload.price == 280010 and sell.display.order_type == "LIMIT"


async def test_price_outside_circuit_refused():
    w = build_world()
    with pytest.raises(OrderRefused) as info:
        await w.builder.build_place(D(action="BUY", symbol_query="RELIANCE", quantity=1, order_type="LIMIT", limit_price="3500"))
    assert "outside today's allowed range" in info.value.message


async def test_sell_half_of_seven_is_three_with_rounding_stated():
    w = build_world()
    w.fake.holdings = [{"isin": "INE467B01029", "symbol": "TCS", "freeQty": 7, "btstQty": 0, "sellQty": 0, "price": 1, "prevClose": 1}]
    built = await w.builder.build_place(D(action="SELL", symbol_query="TCS", quantity_mode="HALF"))
    assert built.payload.qty == -3 and built.payload.product == "CNC"
    assert any("Half of your 7" in n and "rounded down" in n for n in built.display.notices)
    assert built.source_check["kind"] == "HOLDING" and built.source_check["qty"] == 7


async def test_sell_half_of_one_is_refused():
    w = build_world()
    w.fake.holdings = [{"isin": "INE467B01029", "symbol": "TCS", "freeQty": 1, "btstQty": 0, "sellQty": 0, "price": 1, "prevClose": 1}]
    with pytest.raises(OrderRefused) as info:
        await w.builder.build_place(D(action="SELL", symbol_query="TCS", quantity_mode="HALF"))
    assert "rounds down to 0" in info.value.message


async def test_holding_and_intraday_position_both_present_asks_which():
    w = build_world()
    w.fake.holdings = [{"isin": "INE467B01029", "symbol": "TCS", "freeQty": 10, "btstQty": 0, "sellQty": 0, "price": 1, "prevClose": 1}]
    w.fake.positions = [{"exchange": "NSECM", "token": 11536, "product": "INTRADAY", "netQuantity": 4, "netPrice": 1}]
    with pytest.raises(NeedsClarification) as info:
        await w.builder.build_place(D(action="SELL", symbol_query="TCS", quantity_mode="ALL"))
    assert len(info.value.options) == 2
    built = await w.builder.build_place(D(action="SELL", symbol_query="TCS", quantity_mode="ALL", product="INTRADAY"))
    assert built.payload.qty == -4 and built.payload.product == "INTRADAY"


async def test_selling_more_than_held_on_cnc_refused_and_short_needs_explicit_word():
    w = build_world()
    w.fake.holdings = [{"isin": "INE009A01021", "symbol": "INFY", "freeQty": 2, "btstQty": 0, "sellQty": 0, "price": 1, "prevClose": 1}]
    with pytest.raises(OrderRefused) as info:
        await w.builder.build_place(D(action="SELL", symbol_query="INFY", quantity=5))
    assert "at most 2" in info.value.message
    with pytest.raises(OrderRefused):
        await w.builder.build_place(D(action="SELL", symbol_query="TCS", quantity=5, product="INTRADAY"))
    short = await w.builder.build_place(D(action="SELL", symbol_query="TCS", quantity=5, short=True))
    assert short.payload.product == "INTRADAY" and short.payload.qty == -5


async def test_option_lots_to_units_and_nearest_expiry():
    w = build_world()
    built = await w.builder.build_place(D(action="BUY", symbol_query="NIFTY", instrument_kind="OPTION", strike="24500",
                                          option_type="CE", quantity=2, quantity_mode="LOTS", order_type="LIMIT", limit_price="145.50"))
    assert built.payload.exchange == "NSEFO" and built.payload.product == "NRML" and built.payload.qty == 150
    assert built.display.lots == 2 and built.display.lot_size == 75
    assert any("Expiry" in n and "nearest" in n for n in built.display.notices)


async def test_fo_units_not_lot_multiple_refused_and_freeze_limit():
    w = build_world()
    with pytest.raises(OrderRefused) as info:
        await w.builder.build_place(D(action="BUY", symbol_query="NIFTY", instrument_kind="OPTION", strike="24500", option_type="CE",
                                      quantity=100, order_type="LIMIT", limit_price="100"))
    assert "multiple of the lot size 75" in info.value.message
    with pytest.raises(OrderRefused) as info:
        await w.builder.build_place(D(action="BUY", symbol_query="NIFTY", instrument_kind="OPTION", strike="24500", option_type="CE",
                                      quantity=25, quantity_mode="LOTS", order_type="LIMIT", limit_price="100"))
    assert "freeze limit" in info.value.message


async def test_cnc_on_fo_refused():
    w = build_world()
    with pytest.raises(OrderRefused):
        await w.builder.build_place(D(action="BUY", symbol_query="NIFTY", instrument_kind="OPTION", strike="24500", option_type="PE",
                                      quantity=1, quantity_mode="LOTS", product="CNC", order_type="LIMIT", limit_price="100"))


async def test_stop_loss_rules_checked_against_ltp():
    w = build_world()
    w.fake.holdings = [{"isin": "INE040A01034", "symbol": "HDFCBANK", "freeQty": 10, "btstQty": 0, "sellQty": 0, "price": 1, "prevClose": 1}]
    ok = await w.builder.build_place(D(action="SELL", symbol_query="HDFCBANK", quantity=10, order_type="SL", trigger_price="1600", limit_price="1595"))
    assert ok.payload.book == "SL" and ok.payload.trigger == 160000 and ok.payload.price == 159500
    with pytest.raises(OrderRefused) as info:  # sell SL trigger above LTP 1,650
        await w.builder.build_place(D(action="SELL", symbol_query="HDFCBANK", quantity=10, order_type="SL", trigger_price="1700", limit_price="1700"))
    assert "trigger below the current price" in info.value.message


async def test_market_closed_becomes_labelled_amo():
    w = build_world(market_open=False)
    built = await w.builder.build_place(D(action="BUY", symbol_query="INFY", quantity=1))
    assert built.payload.amo is True and built.display.amo and any("AMO" in n for n in built.display.notices)
    assert built.reference_ltp is None  # no drift check for a queued AMO


async def test_limits_and_kill_switch():
    w = build_world(overrides={"MaxOrderValuePaise": 1_000_000})
    with pytest.raises(OrderRefused) as info:
        await w.builder.build_place(D(action="BUY", symbol_query="RELIANCE", quantity=10))
    assert "safety limit" in info.value.message
    w.settings_overrides["TradingKillSwitch"] = True
    with pytest.raises(OrderRefused) as info:
        await w.builder.build_place(D(action="BUY", symbol_query="INFY", quantity=1))
    assert "kill switch" in info.value.message
    w2 = build_world(overrides={"AllowedExchanges": "NSE"})
    with pytest.raises(OrderRefused):
        await w2.builder.build_place(D(action="BUY", symbol_query="NIFTY", instrument_kind="OPTION", strike="24500", option_type="CE",
                                       quantity=1, quantity_mode="LOTS", order_type="LIMIT", limit_price="100"))


async def test_no_live_price_refuses_market_order():
    w = build_world()
    w.cache.on_disconnected()
    w.cache._quotes.clear()
    with pytest.raises(OrderRefused) as info:
        await w.builder.build_place(D(action="BUY", symbol_query="INFY", quantity=1))
    assert "no live price" in info.value.message


# ── modify / cancel ──

def _open_order(w, **kw):
    order = {"orderId": 5001, "time": 0, "token": 1333, "exchange": "NSECM", "product": "CNC", "qtyRemaining": -10, "qtyTraded": 0,
             "price": 159500, "triggerPrice": 160000, "book": "SL", "validity": "Day", "status": "Pending", "reason": "", "amo": False}
    order.update(kw)
    w.fake.orders.insert(0, order)
    return order


async def test_move_stop_loss_up_builds_full_new_state():
    w = build_world()
    _open_order(w)
    built = await w.builder.build_modify(OrderChangeDraft(symbol_query="HDFCBANK", stop_loss_only=True, new_trigger_price="1640"))
    assert built.target_order_id == "5001" and built.kind == "MODIFY"
    # Full new state; the 1,595 limit stays valid for a sell SL (price <= trigger), so it is kept.
    assert built.payload.to_request_json() == {"exchange": "NSE", "token": 1333, "qty": -10, "price": 159500, "book": "SL",
                                               "product": "CNC", "validity": "Day", "trigger": 164000}
    assert any("Trigger" in n for n in built.display.notices)


async def test_moving_buy_stop_loss_keeps_limit_valid():
    w = build_world()
    _open_order(w, qtyRemaining=10, triggerPrice=170000, price=170500)  # buy SL above LTP 1,650
    built = await w.builder.build_modify(OrderChangeDraft(symbol_query="HDFCBANK", new_trigger_price="1720"))
    assert built.payload.trigger == 172000 and built.payload.price == 172000  # raised so price >= trigger


async def test_modify_with_two_matching_orders_asks_and_none_refuses():
    w = build_world()
    _open_order(w)
    _open_order(w, orderId=5002, triggerPrice=158000, price=157500)
    with pytest.raises(NeedsClarification) as info:
        await w.builder.build_modify(OrderChangeDraft(symbol_query="HDFCBANK", new_trigger_price="1640"))
    assert len(info.value.options) == 2
    with pytest.raises(OrderRefused):
        await w.builder.build_modify(OrderChangeDraft(symbol_query="INFY", new_limit_price="1500"))


async def test_filled_order_cannot_be_modified():
    w = build_world()
    _open_order(w, status="Executed", qtyRemaining=0, qtyTraded=10)
    with pytest.raises(OrderRefused) as info:
        await w.builder.build_modify(OrderChangeDraft(symbol_query="HDFCBANK", new_trigger_price="1640"))
    assert "Only pending orders" in info.value.message and "Executed" in info.value.message


async def test_cancel_by_description():
    w = build_world()
    _open_order(w, token=1594, book="RL", triggerPrice=0, price=150000, qtyRemaining=5, product="CNC")
    built = await w.builder.build_cancel(OrderChangeDraft(symbol_query="INFY", side="BUY"))
    assert built.kind == "CANCEL" and built.target_order_id == "5001" and built.display.action == "CANCEL"
