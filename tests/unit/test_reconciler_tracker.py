"""Reconciler (unknown outcomes, boot recovery) and tracker (socket events, REST catch-up, late links)."""
from datetime import timedelta

import httpx

from domains.marketdata.domain.packets import parse_order_frame
from shared.contracts.orders import JournalEntry, OrderDraft
from tests.fakes.market import nse_order_frame
from tests.fakes.orders_world import USER, build_world, now_utc

BUY_INFY = OrderDraft(action="BUY", symbol_query="INFY", quantity=3)


async def _unknown(w, *, booked: bool):
    p = await w.propose(BUY_INFY)
    w.fake.fail_next("/orders", method="POST", exc=httpx.ReadTimeout, accept_first=booked)
    outcome = await w.execution.approve(p.id, USER, p.payload_hash)
    assert outcome.journal.state == "UNKNOWN"
    return outcome.journal


async def test_unknown_not_booked_becomes_not_placed_after_all_attempts():
    w = build_world()
    entry = await _unknown(w, booked=False)
    for _ in range(4):
        await w.reconciler.run_once(force=True)
    final = await w.store.get_journal(entry.id)
    assert final.state == "NOT_PLACED" and final.reconcile_attempts >= 3
    assert w.fake.count("POST", "/orders") == 1


async def test_two_identical_unlinked_orders_are_ambiguous_never_resent():
    w = build_world()
    entry = await _unknown(w, booked=True)
    w.fake._book_order(entry.payload.to_request_json())  # e.g. placed manually in the 021 app meanwhile
    changed = await w.reconciler.run_once(force=True)
    assert changed[0].state == "AMBIGUOUS" and "several 021 orders" in changed[0].reason
    assert w.fake.count("POST", "/orders") == 1


async def test_already_linked_order_is_not_reused():
    w = build_world()
    p1 = await w.propose(BUY_INFY)
    assert (await w.execution.approve(p1.id, USER, p1.payload_hash)).status == "sent"  # order 1001 linked
    entry = await _unknown(w, booked=False)  # identical payload, nothing booked
    for _ in range(4):
        await w.reconciler.run_once(force=True)
    assert (await w.store.get_journal(entry.id)).state == "NOT_PLACED"


async def test_boot_recovery_reconciles_rows_left_sending():
    w = build_world()
    p = await w.propose(BUY_INFY)
    now = now_utc()
    journal = JournalEntry(proposal_id=p.id, user_id=USER, action="PLACE", payload=p.payload, payload_hash=p.payload_hash,
                           sent_at=now, updated_at=now)
    assert (await w.store.claim(p.id, USER, p.payload_hash, now, journal)).ok
    w.fake._book_order(p.payload.to_request_json())  # the send reached 021, then the server died
    assert await w.reconciler.recover_on_boot() == 1
    changed = await w.reconciler.run_once()
    assert changed[0].state == "ACKED" and changed[0].order_id == "1001"
    assert w.fake.count("POST", "/orders") == 0  # recovery never sends


async def test_unknown_cancel_where_order_filled_first():
    w = build_world()
    w.fake.orders.insert(0, {"orderId": 7003, "time": 0, "token": 1594, "exchange": "NSECM", "product": "CNC", "qtyRemaining": 5,
                             "qtyTraded": 0, "price": 150000, "triggerPrice": 0, "book": "RL", "validity": "Day", "status": "Pending"})
    from shared.contracts.orders import OrderChangeDraft

    cp = await w.proposals.create(USER, await w.builder.build_cancel(OrderChangeDraft(symbol_query="INFY")))
    w.fake.fail_next("/orders/7003", method="DELETE", status=503)
    out = await w.execution.approve(cp.id, USER, cp.payload_hash)
    assert out.journal.state == "UNKNOWN"
    w.fake.fill(7003, 5, 150000)
    changed = await w.reconciler.run_once(force=True)
    assert changed[0].state == "NOT_PLACED" and changed[0].reason == "filled before the cancel arrived"


async def test_socket_trade_event_updates_fill_from_rest_truth():
    w = build_world()
    p = await w.propose(BUY_INFY)
    sent = await w.execution.approve(p.id, USER, p.payload_hash)
    w.fake.fill(1001, 3, 153100)
    packet = parse_order_frame(nse_order_frame(1, w.fake.ucc, "INFY", 1001, 3, 153100))
    await w.tracker.on_packet(packet)
    entry = await w.store.get_journal(sent.journal.id)
    assert entry.order_status == "Executed" and entry.filled_qty == 3 and entry.avg_fill_price == 153100
    assert w.hub.sent[-1][1]["order"]["order_status"] == "Executed"


async def test_rejection_reason_from_socket_and_other_ucc_ignored():
    w = build_world()
    p = await w.propose(BUY_INFY)
    sent = await w.execution.approve(p.id, USER, p.payload_hash)
    w.fake.orders[0].update({"status": "Rejected", "reason": "Price outside circuit"})
    await w.tracker.on_packet(parse_order_frame(nse_order_frame(3, "HACK9999", "INFY", 1001, 3, 0, "x")))
    assert (await w.store.get_journal(sent.journal.id)).order_status != "Rejected"  # not our account
    await w.tracker.on_packet(parse_order_frame(nse_order_frame(3, w.fake.ucc, "INFY", 1001, 3, 0, "Price outside circuit")))
    entry = await w.store.get_journal(sent.journal.id)
    assert entry.order_status == "Rejected" and entry.reason == "Price outside circuit"


async def test_catch_up_after_reconnect_uses_rest():
    w = build_world()
    p = await w.propose(BUY_INFY)
    sent = await w.execution.approve(p.id, USER, p.payload_hash)
    w.fake.fill(1001, 3, 153000)  # happened while the socket was down: no event
    assert await w.tracker.catch_up() == 1
    assert (await w.store.get_journal(sent.journal.id)).order_status == "Executed"


async def test_late_order_after_not_placed_is_linked_and_reported():
    w = build_world()
    entry = await _unknown(w, booked=False)
    for _ in range(4):
        await w.reconciler.run_once(force=True)
    assert (await w.store.get_journal(entry.id)).state == "NOT_PLACED"
    w.fake._book_order(entry.payload.to_request_json())  # 021 books it very late
    await w.tracker.on_packet(parse_order_frame(nse_order_frame(2, w.fake.ucc, "INFY", 1001, 3, 0)))
    late = await w.store.get_journal(entry.id)
    assert late.state == "ACKED" and late.order_id == "1001" and "appeared after" in late.reason
    assert "order_late_link" in w.audit.kinds()


async def test_reconcile_schedule_waits_between_attempts():
    w = build_world()
    entry = await _unknown(w, booked=False)
    assert await w.reconciler.run_once() == []  # not due yet (first check at +2 s)
    w.reconciler._now = lambda: now_utc() + timedelta(seconds=3)
    await w.reconciler.run_once()
    assert (await w.store.get_journal(entry.id)).reconcile_attempts == 1
