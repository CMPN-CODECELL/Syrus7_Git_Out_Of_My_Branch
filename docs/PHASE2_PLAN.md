# Phase 2 plan: L2 orders with confirmation

**Status: built.** All nine pieces exist, and the exit test `tests/unit/test_l2_exit.py` passes. The design below is what the code implements.

**Goal:** "Buy 10 Reliance at market", "Sell half my TCS", "Move my stop-loss on HDFC Bank up to 1640" and "Cancel my Infosys buy" each produce an exact order card. The order goes to 021 only after the trader clicks Approve on that card.

**Exit test:** zero duplicate orders across 200 runs with random timeouts, and the sent payload always equals the approved payload (`tests/unit/test_l2_exit.py`).

Decisions agreed with the team: offer AMO (labelled on the card) when the market is closed; live updates over a per-user WebSocket with a polling fallback; no CSRF token (Bearer-header auth, see [DECISIONS.md](DECISIONS.md) ADR-011); build all nine pieces.

## Flow

```
chat ─▶ Gemini ─▶ draft_order / draft_modify_order / draft_cancel_order   (draft tools: no send)
                     │
                     ▼
               OrderBuilder (deterministic)
               resolve → quantity → price/tick → product → checks → OrderPayload
                     │  question / refusal goes back to chat
                     ▼
               ProposalService ─▶ kraken_proposals (PROPOSED, payload_hash, expires +60 s)
                     │
UI card ◀── GET /v1/proposals/{id}      (rendered from the row, never from LLM text)
UI Approve ─▶ POST /v1/proposals/{id}/approve {payload_hash}
                     │  Origin allowlist, JSON only, owner, not expired, hash match,
                     │  kill switch, instruments fresh, price drift ≤ 0.5% (else re-quote),
                     │  source quantity unchanged ("sell half")
                     ▼
               store.claim(): PROPOSED→APPROVED + journal row SENDING   (one transaction)
                     ▼
               ExecutionService ─▶ 021 (exactly one attempt, sends serialised)
                     ├ ACKED (orderId)         ├ REJECTED (021 reason)
                     ├ NOT_SENT (never left)   └ UNKNOWN ─▶ Reconciler (GET /orders) ─▶ ACKED | NOT_PLACED | AMBIGUOUS
                     ▼
               Orders socket + REST catch-up ─▶ OrderTracker ─▶ journal ─▶ user WebSocket hub
```

## Pieces

| # | Piece | Code |
|---|---|---|
| 1 | Draft tools | `domains/copilot/application/draft_tools.py`, `tool_specs.py` |
| 2 | Order builder and validator | `domains/copilot/application/order_builder.py`, `domains/copilot/domain/parsing.py` |
| 3 | Proposal store | `domains/orders/ports.py`, `infrastructure/memory_store.py`, `infrastructure/pg_store.py`, migration `kraken_002` |
| 4 | Approve / reject API | `domains/orders/api/router.py` |
| 5 | Execution service and journal | `domains/orders/application/execution.py` |
| 6 | Reconciler | `domains/orders/application/reconciler.py` |
| 7 | Orders socket client | `domains/marketdata/infrastructure/orders_socket.py`, `domains/orders/application/tracker.py` |
| 8 | Live push | `domains/orders/application/hub.py`, WS `/v1/stream/orders` |
| 9 | Audit table | `kraken_audit_log` (append-only trigger), `AuditSink` |

## Builder rules

| Input | Rule |
|---|---|
| No quantity | Ask. Never default. |
| LOTS | units = lots × `board_lot_quantity`; the card shows both |
| HALF / ALL | From the holding (free + btst − already sold) or the opposite-side position. Half rounds down (to lots for F&O); 0 → refuse. Holding and intraday position both present with no product given → ask. |
| Price text | Code parses it ("₹2,800.50", "2.8k", "2,80,000"). Rounded to tick in the trader's favour (buy down, sell up) with a notice. Outside the price limits (circuits) → refuse. |
| MARKET | `price = 0`; card shows the 021 reference LTP and an estimated value |
| SL | Buy: trigger > LTP and price ≥ trigger. Sell: trigger < LTP and price ≤ trigger. |
| Product | Explicit, or the closed position's product, or CNC (cash) / NRML (F&O) |
| F&O qty | Lot multiple; above freeze quantity → refuse with "max N per order" |
| Index | Refuse (data only) and suggest futures/options |
| Sell without holding or position | Refuse unless the trader explicitly said "short" (then INTRADAY) |
| Market closed | AMO (`amo: true`), labelled on the card |
| Limits | `TRADING_KILL_SWITCH`, `MAX_ORDER_QTY`, `MAX_ORDER_VALUE_PAISE`, `ALLOWED_EXCHANGES`, `ALLOWED_PRODUCTS`, checked at build **and** at approve |
| Modify / cancel | Find open orders for the symbol (side and SL hints narrow it). 0 → refuse; more than 1 → ask with a list; partially filled → refuse modify. Modify sends the full new state. |

## Journal states

`SENDING → ACKED | REJECTED | NOT_SENT | UNKNOWN`. `UNKNOWN → ACKED | NOT_PLACED | AMBIGUOUS` via the reconciler. ACKED rows then follow 021's order status (Pending, Executed, Rejected, Cancelled, …) from the orders socket, with REST as the source of truth.

A PLACE in UNKNOWN is matched on token, exchange, product, |qty|, price and `time ≥ sent_at − 30 s`, among orderIds not already linked. Attempts run at about 2/5/10/20 s; with no match the row becomes NOT_PLACED, and two or more matches make it AMBIGUOUS (shown to the trader, never resent). SENDING rows left by a crash are reconciled at boot.

## API

| Method | Path | Notes |
|---|---|---|
| GET | `/v1/proposals/{id}` | card data (owner only) |
| POST | `/v1/proposals/{id}/approve` | body `{"payload_hash": "..."}`; JSON only; Origin allowlist |
| POST | `/v1/proposals/{id}/reject` | |
| GET | `/v1/orders` | the user's journal (polling fallback) |
| GET | `/v1/orders/{journal_id}` | |
| WS | `/v1/stream/orders` | first message `{"type":"auth","token":"<jwt>"}`; pushes `order_update` |

## Tests

- **Builder:** every rule above.
- **Parsing:** prices, ticks, expiries.
- **Store CAS:** double approve, expiry, hash mismatch.
- **Execution:** each outcome.
- **Reconciler:** found, not placed, ambiguous, boot recovery.
- **Tracker:** socket events, catch-up.
- **API:** auth, Origin, JSON-only, owner checks.
- **Chat:** draft tools never call broker order methods.
- **L2 exit:** 200 runs with random order timeouts and concurrent double-approves; asserts zero duplicates and that the payload sent to 021 equals the approved one.
