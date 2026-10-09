"""Approval and execution: one-time approval, exact payload, every send outcome."""
import asyncio
from datetime import timedelta

import httpx

from shared.contracts.orders import OrderDraft
from tests.fakes.orders_world import USER, build_world, now_utc

BUY_INFY = OrderDraft(action="BUY", symbol_query="INFY", quantity=3)


async def test_approve_sends_exactly_the_approved_payload_once():
    w = build_world()
    p = await w.propose(BUY_INFY)
    outcome = await w.execution.approve(p.id, USER, p.payload_hash)
    assert outcome.status == "sent" and outcome.journal.state == "ACKED" and outcome.journal.order_id == "1001"
    assert w.fake.order_bodies == [p.payload.to_request_json()]
    again = await w.execution.approve(p.id, USER, p.payload_hash)
    assert again.status == "refused" and again.http_status == 409
    assert len(w.fake.order_bodies) == 1
    kinds = w.audit.kinds()
    for kind in ("proposal_created", "approval_attempt", "proposal_approved", "order_send", "order_result"):
        assert kind in kinds
    assert w.hub.sent and w.hub.sent[-1][1]["type"] == "order_update"


async def test_concurrent_double_click_sends_once():
    w = build_world()
    p = await w.propose(BUY_INFY)
    results = await asyncio.gather(*(w.execution.approve(p.id, USER, p.payload_hash) for _ in range(5)))
    assert sorted(r.status for r in results).count("sent") == 1
    assert len(w.fake.order_bodies) == 1


async def test_other_user_cannot_approve():
    w = build_world()
    p = await w.propose(BUY_INFY)
    outcome = await w.execution.approve(p.id, "someone-else", p.payload_hash)
    assert outcome.http_status == 404 and not w.fake.order_bodies


async def test_hash_mismatch_refused():
    w = build_world()
    p = await w.propose(BUY_INFY)
    outcome = await w.execution.approve(p.id, USER, "0" * 64)
    assert outcome.http_status == 409 and not w.fake.order_bodies


async def test_expired_card_refused():
    w = build_world()
    p = await w.propose(BUY_INFY)
    w.execution._now = lambda: now_utc() + timedelta(seconds=61)
    outcome = await w.execution.approve(p.id, USER, p.payload_hash)
    assert outcome.http_status == 410 and not w.fake.order_bodies
    assert (await w.store.get_proposal(p.id)).state == "EXPIRED"


async def test_price_drift_over_half_percent_requotes_without_sending():
    w = build_world()
    p = await w.propose(BUY_INFY)
    w.set_price((1, 1594), 154000)  # +0.65%
    outcome = await w.execution.approve(p.id, USER, p.payload_hash)
    assert outcome.status == "requote" and not w.fake.order_bodies
    assert outcome.new_proposal is not None and outcome.new_proposal.reference_ltp == 154000
    assert (await w.store.get_proposal(p.id)).state == "EXPIRED"


async def test_small_drift_is_fine():
    w = build_world()
    p = await w.propose(BUY_INFY)
    w.set_price((1, 1594), 153500)  # +0.33%
    assert (await w.execution.approve(p.id, USER, p.payload_hash)).status == "sent"


async def test_source_quantity_changed_aborts_sell_half():
    w = build_world()
    w.fake.holdings = [{"isin": "INE467B01029", "symbol": "TCS", "freeQty": 8, "btstQty": 0, "sellQty": 0, "price": 1, "prevClose": 1}]
    p = await w.propose(OrderDraft(action="SELL", symbol_query="TCS", quantity_mode="HALF"))
    w.fake.holdings[0]["freeQty"] = 2
    outcome = await w.execution.approve(p.id, USER, p.payload_hash)
    assert outcome.status == "refused" and "changed from 8 to 2" in outcome.message and not w.fake.order_bodies


async def test_kill_switch_blocks_approval():
    w = build_world()
    p = await w.propose(BUY_INFY)
    w.settings_overrides["TradingKillSwitch"] = True
    outcome = await w.execution.approve(p.id, USER, p.payload_hash)
    assert outcome.http_status == 423 and not w.fake.order_bodies


async def test_stale_instruments_block_approval():
    w = build_world()
    p = await w.propose(BUY_INFY)
    w.instruments.loaded_for = None
    outcome = await w.execution.approve(p.id, USER, p.payload_hash)
    assert outcome.status == "refused" and "instrument list is out of date" in outcome.message


async def test_risk_rejection_is_recorded_with_reason():
    w = build_world()
    p = await w.propose(BUY_INFY)
    w.fake.fail_next("/orders", method="POST", status=500, error="Insufficient funds")
    outcome = await w.execution.approve(p.id, USER, p.payload_hash)
    assert outcome.status == "rejected" and outcome.journal.reason == "Insufficient funds"


async def test_connect_error_is_not_sent():
    w = build_world()
    p = await w.propose(BUY_INFY)
    await w.client.get_positions()
    w.fake.fail_next("/orders", method="POST", exc=httpx.ConnectError)
    outcome = await w.execution.approve(p.id, USER, p.payload_hash)
    assert outcome.status == "not_sent" and outcome.journal.state == "NOT_SENT"


async def test_timeout_after_accept_is_unknown_then_reconciled_never_resent():
    w = build_world()
    p = await w.propose(BUY_INFY)
    w.fake.fail_next("/orders", method="POST", exc=httpx.ReadTimeout, accept_first=True)
    outcome = await w.execution.approve(p.id, USER, p.payload_hash)
    assert outcome.status == "unknown" and outcome.journal.state == "UNKNOWN"
    changed = await w.reconciler.run_once(force=True)
    assert changed and changed[0].state == "ACKED" and changed[0].order_id == "1001"
    assert w.fake.count("POST", "/orders") == 1


async def test_modify_and_cancel_go_to_the_target_order():
    w = build_world()
    w.fake.orders.insert(0, {"orderId": 7001, "time": 0, "token": 1594, "exchange": "NSECM", "product": "CNC", "qtyRemaining": 5,
                             "qtyTraded": 0, "price": 150000, "triggerPrice": 0, "book": "RL", "validity": "Day", "status": "Pending"})
    from shared.contracts.orders import OrderChangeDraft

    built = await w.builder.build_modify(OrderChangeDraft(symbol_query="INFY", new_limit_price="1510"))
    mp = await w.proposals.create(USER, built)
    out = await w.execution.approve(mp.id, USER, mp.payload_hash)
    assert out.status == "sent" and w.fake.orders[0]["price"] == 151000 and w.fake.count("PUT", "/orders/7001") == 1
    cancel = await w.builder.build_cancel(OrderChangeDraft(symbol_query="INFY"))
    cp = await w.proposals.create(USER, cancel)
    out = await w.execution.approve(cp.id, USER, cp.payload_hash)
    assert out.status == "sent" and w.fake.orders[0]["status"] == "Cancelled"


async def test_order_filled_before_cancel_approval_is_refused():
    w = build_world()
    w.fake.orders.insert(0, {"orderId": 7002, "time": 0, "token": 1594, "exchange": "NSECM", "product": "CNC", "qtyRemaining": 5,
                             "qtyTraded": 0, "price": 150000, "triggerPrice": 0, "book": "RL", "validity": "Day", "status": "Pending"})
    from shared.contracts.orders import OrderChangeDraft

    cp = await w.proposals.create(USER, await w.builder.build_cancel(OrderChangeDraft(symbol_query="INFY")))
    w.fake.fill(7002, 5, 150000)
    out = await w.execution.approve(cp.id, USER, cp.payload_hash)
    assert out.status == "refused" and "Executed" in out.message and w.fake.count("DELETE", "/orders/7002") == 0
