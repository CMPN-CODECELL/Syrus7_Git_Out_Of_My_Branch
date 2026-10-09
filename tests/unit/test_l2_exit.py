"""
Phase 2 exit test (docs/PHASE2_PLAN.md):
  zero duplicate orders across 200 runs with random timeouts, and the payload 021 receives is
  always byte-for-byte the payload the trader approved.

Each run proposes a BUY with a unique quantity (so every 021 order is attributable), then fires two
concurrent approvals (a double click). The fake 021 injects, on 40% of order POSTs, one of:
timeout after booking, timeout before booking, 503 without booking, or a risk rejection; plus 10%
random 500/503/429 on every call. Afterwards the reconciler resolves every unknown outcome.
"""
import asyncio
import hashlib
import json
from collections import Counter

from shared.contracts.orders import OrderDraft
from tests.fakes.orders_world import USER, build_world

RUNS = 200


async def test_zero_duplicates_and_exact_payloads_under_random_send_faults():
    w = build_world(seed=21, overrides={"MaxOrderValuePaise": 10**12})
    w.fake.order_fault_rate = 0.4
    w.fake.random_fault_rate = 0.1

    proposals = {}
    for i in range(RUNS):
        p = await w.propose(OrderDraft(action="BUY", symbol_query="INFY", quantity=i + 1))
        proposals[p.payload.qty] = p
        results = await asyncio.gather(*(w.execution.approve(p.id, USER, p.payload_hash) for _ in range(2)))
        assert sum(r.journal is not None for r in results) == 1, "a proposal was executed twice"

    for _ in range(6):  # reconciler passes until every unknown outcome is resolved
        await w.reconciler.run_once(force=True)

    journal = w.store.all_journal()
    assert len(journal) == RUNS

    # 1. No duplicates: every quantity was booked by 021 at most once.
    booked = Counter(body["qty"] for body in w.fake.order_bodies)
    assert booked and max(booked.values()) == 1

    # 2. Exact payloads: what 021 booked is exactly the approved payload (same canonical hash).
    for body in w.fake.order_bodies:
        p = proposals[body["qty"]]
        assert body == p.payload.to_request_json()
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        assert hashlib.sha256(canonical).hexdigest() == p.payload_hash

    # 3. The journal tells the truth: ACKED exactly when 021 booked it; nothing left unresolved.
    order_qty = {str(o["orderId"]): abs(o["qtyRemaining"]) + o["qtyTraded"] for o in w.fake.orders}
    for entry in journal:
        assert entry.state in ("ACKED", "REJECTED", "NOT_SENT", "NOT_PLACED"), entry.state
        was_booked = booked.get(entry.payload.qty, 0) == 1
        assert (entry.state == "ACKED") == was_booked, (entry.state, entry.reason)
        if entry.state == "ACKED":
            assert order_qty[entry.order_id] == entry.payload.qty

    # 4. The run really exercised every failure mode, and no order POST was ever retried.
    assert set(w.fake.fault_log) == set(w.fake.order_fault_modes)
    assert w.fake.count("POST", "/orders") <= RUNS
