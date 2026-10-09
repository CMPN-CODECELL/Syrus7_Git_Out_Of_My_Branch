# Kraken roadmap

Depth before breadth: a solid Level 2 beats a shaky Level 4. Each phase must pass its exit check ([TESTING.md](TESTING.md#phase-exit-criteria)) under fault injection before the next one starts.

| Phase | Scope | Status |
|---|---|---|
| 0 | Repo cleanup, infra and auth fixes, shared contracts, CI, honest README | **done** |
| 1 | 021 gateway, instruments, market socket, analysis feed, L1 read tools, chat API | **done** |
| 2 | L2 orders with confirmation | next |
| 3 | L3 standing instructions | planned |
| 4 | L4 multi-step plans | planned |
| 5 | Hardening, evals, red-team, demo and viva prep | planned |

## Owners (team split)

| Member | Area | Paths |
|---|---|---|
| A | Broker gateway & reliability | `domains/broker/`, `tests/fakes/fake_021.py` |
| B | Market data, analysis feed, L3 trigger engine | `domains/marketdata/`, `domains/historical/`, `domains/ingestion/`, (planned) `domains/instructions/` |
| C | Copilot brain: LLM, order builder, validator, planners | `domains/copilot/`, technicals engine, (planned) `tests/evals/` |
| D | Chat UI, app API, proposal store, security, docs | `frontend/`, (planned) `domains/app_api/`, `README.md`, `docs/` |

Seams to agree before coding (the contracts live in [shared/contracts](../shared/contracts)):

| Seam | Pair | Contract |
|---|---|---|
| Approve → send | D + A | `ExecutionService.execute(proposal_id) → JournalEntry`. D guarantees one-time approval; A guarantees no blind resend |
| Draft → proposal | C + D | `OrderProposal`; the card renders only from proposal fields |
| "If X then Y" → trigger | C + B | `StandingInstruction` / `TriggerCondition` |
| Fill events → UI | B + D | `OrderEvent` on the WS hub, keyed by orderId |
| Candles → indicator tools | B + C | `CandleService.get_daily → CandleSeries` |

## Phase 2: orders with confirmation

1. **Draft tools for the LLM** (`draft_order`, `draft_modify`, `draft_cancel`) that return an `OrderDraft`. They never send anything.
2. **Order builder and validator** (deterministic):
   - Entity resolution; ask when ambiguous ("HDFC").
   - Quantity math: "half" of 7 is 3 with the rounding stated, "half" of 1 is refused, lots → units, and there is never a default quantity.
   - Price parsing: "₹2,800.50" or "2.8k" → paise, rounded to the tick size with a notice.
   - Checks: circuits, lot multiple, freeze quantity, product/exchange pairs, SL trigger rules against the 021 LTP, funds sanity check, fat-finger limits (`MAX_ORDER_*`), the kill switch, refusing to order an index, and AMO when the market is closed.
3. **Proposal store** in Postgres: immutable row, `payload_hash`, 60 s TTL, state machine.
4. **`POST /proposals/{id}/approve|reject`**: authenticated, CSRF-protected, compare-and-set PROPOSED → APPROVED, hash check, re-quote if LTP drifted more than 0.5%, re-validate position quantity at send time.
5. **Execution service and order journal**: SENDING → ACKED | REJECTED | UNKNOWN. Reconciler for UNKNOWN through `GET /orders` + `GET /trades`, matching on token, qty, price, product and time ≥ sent_at for an orderId not yet linked.
6. **Orders socket client** (the parser already exists), with REST catch-up after reconnects. Push status to the UI over the events WebSocket.
7. **Audit table** (append-only), fed by the REST client's audit hook, proposals and approvals.

**Exit:** zero duplicate orders across 200 runs with random timeouts; the sent payload always equals the displayed payload.

## Phase 3: standing instructions

- Persisted instructions with ACTIVE → FIRING → DONE/FAILED, an atomic claim (`UPDATE … WHERE state='ACTIVE' RETURNING`), and a Postgres advisory lock so only one engine evaluates.
- Crossing semantics. Ask "fire now or wait for a fresh cross?" when the price is already past the level. Pause while the feed is stale.
- Boot recovery: reconcile FIRING rows through `GET /orders` before re-arming.
- Holding-drop alerts (once per holding per day vs prevClose), and indicator conditions on closed bars.
- Rebuild or retire the legacy `domains/notifications` (owner column, no free-form webhooks).

**Exit:** a kill -9 mid-fire, then a restart, gives exactly one order; 1,000 ticks below the level give one order.

## Phase 4: multi-step plans

- Planners: "exit all losing intraday positions" (unrealized < 0, `squareOffQuantity`, shorts included), and "rebalance so no stock exceeds 20%" (sells before buys, whole shares and lots, residual stated).
- A plan card with before/after, one approval (hash over all legs), sequential paced execution and a per-leg report. No silent retries; a crash never re-sends an executed or UNKNOWN leg.

**Exit:** with one leg forced to reject, the report shows exactly which legs filled, which were rejected and why.

## Phase 5: hardening

- Chaos runs against `Fake021`, a 100+ prompt NL eval set, and a prompt-injection red-team set.
- Demo script; viva prep (each member explains another member's module); a change-request drill (ship a mid-day spec change in 45 minutes).
- Pin dependencies, make pip-audit blocking, and stream chat responses.

## Questions for the organisers

- Will the hidden tests run against our deployment with *their* 021 account? (The UCC and password are already configurable via `.env`.)
- Is fault injection on the shared dev sandbox the same as on judging day?
- Are AMO orders in scope for the test scenarios?
- Any limit on LLM providers or on calls leaving the machine?
