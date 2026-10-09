# Kraken

Kraken is an AI trading copilot for the 021 Trade Developer Sandbox (021 Trade Hackathon, problem 021-01 "Copilot, Not Autopilot"). A trader asks questions about their 021 account and gives trading instructions in plain English through a web chat.

**Current scope: Level 1 (read-only questions) and Level 2 (orders with confirmation).** Kraken answers questions about P&L, positions, average prices, option chains and technical indicators. It turns "buy 10 Reliance at market", "sell half my TCS", "move my stop-loss on HDFC Bank up to 1640" and "cancel my Infosys buy" into an exact order card. It sends an order to 021 only when the trader clicks Approve on that card. Levels 3–4 are listed under [Future scope](#future-scope).

Every claim below links to the code that implements it and the test that checks it. If a capability is not in these tables, it is not built.

## Safety design (as built)

The LLM can read and *draft*. It cannot send. The only code path that sends an order to 021 is `POST /v1/proposals/{id}/approve` → `ExecutionService.approve()`, triggered by an authenticated human click.

| Claim | Code | Test |
|---|---|---|
| No LLM tool can send, approve, modify or cancel at the broker; draft tools only create proposal cards | [tool_specs.py](domains/copilot/domain/tool_specs.py), [draft_tools.py](domains/copilot/application/draft_tools.py) | `tests/unit/test_chat_service.py::test_no_tool_can_touch_orders`, `tests/unit/test_chat_drafts.py::test_draft_tool_creates_card_and_never_sends` |
| Tool calls are validated against strict schemas; unknown tools and extra arguments (e.g. `"approve": true`) are refused | [chat_service.py](domains/copilot/application/chat_service.py) | `test_chat_service.py::test_unknown_tool_is_refused`, `test_chat_drafts.py::test_injected_send_instruction_in_args_is_rejected` |
| Tool results reach the LLM wrapped as `untrusted_data`, with an instruction never to follow text inside them | [chat_service.py](domains/copilot/application/chat_service.py), [prompts.py](domains/copilot/application/prompts.py) | `test_chat_service.py::test_tool_results_are_fenced_as_untrusted_data` |
| Third-party symbol text is reduced to a safe charset and at most 24 chars | [read_tools.py](domains/copilot/application/read_tools.py) (`safe_symbol`) | `tests/unit/test_l1_read_tools.py::test_injected_symbol_text_is_neutralised` |
| A reply claiming an order was placed/sent/approved is replaced; "yes"/"confirm" in chat approves nothing | [chat_service.py](domains/copilot/application/chat_service.py) | `test_chat_service.py::test_replies_claiming_an_order_action_are_replaced`, `::test_typing_confirm_does_nothing_special` |
| The LLM never converts money: prices and expiries travel as the trader's text and are parsed by code | [parsing.py](domains/copilot/domain/parsing.py) | `tests/unit/test_parsing.py` |
| Proposals are immutable server rows bound to the SHA-256 of the canonical payload; the card renders from the row | [orders.py](shared/contracts/orders.py), [proposals.py](domains/orders/application/proposals.py) | `tests/unit/test_contracts.py`, `tests/unit/test_orders_api.py::test_card_then_approve_sends_once` |
| Approval is single-use (atomic PROPOSED → APPROVED plus journal row), owner-only, hash-checked and expires after 60 s | [execution.py](domains/orders/application/execution.py), [memory_store.py](domains/orders/infrastructure/memory_store.py), [pg_store.py](domains/orders/infrastructure/pg_store.py) | `tests/unit/test_execution.py::test_concurrent_double_click_sends_once`, `::test_other_user_cannot_approve`, `::test_hash_mismatch_refused`, `::test_expired_card_refused` |
| Price moved more than 0.5% since the card was shown → nothing sent, a fresh card is offered | [order_builder.py](domains/copilot/application/order_builder.py) (`pre_send_check`) | `test_execution.py::test_price_drift_over_half_percent_requotes_without_sending` |
| "Sell half" is re-checked at approval; if the holding changed, nothing is sent | `pre_send_check` | `test_execution.py::test_source_quantity_changed_aborts_sell_half` |
| Kill switch and per-order limits (value, quantity, exchanges, products) enforced at draft time **and** approval time | [order_builder.py](domains/copilot/application/order_builder.py), [execution.py](domains/orders/application/execution.py) | `tests/unit/test_order_builder.py::test_limits_and_kill_switch`, `test_execution.py::test_kill_switch_blocks_approval` |
| Orders are blocked when the instrument list is not from today | `pre_send_check` | `test_execution.py::test_stale_instruments_block_approval` |
| Every proposal, approval attempt, send, result, reconciliation and socket event goes to an append-only audit table | [migration_kraken_002_orders.sql](scripts/migration_kraken_002_orders.sql) (trigger blocks UPDATE/DELETE), [pg_store.py](domains/orders/infrastructure/pg_store.py) | `test_execution.py::test_approve_sends_exactly_the_approved_payload_once` (event kinds) |

## L1 questions Kraken answers

All portfolio and price data comes from 021. Prices are integer paise internally and are shown as ₹.

| Question | Tool | Definition reported with the answer | Test |
|---|---|---|---|
| "What's my P&L today?" | `get_pnl` | unrealized = (LTP − average price) × open qty; realized = today's matched buy/sell trades; holdings P&L and day change vs previous close | `test_l1_read_tools.py::test_q1_pnl_today` |
| "Which positions are down more than 5%?" | `filter_positions` | move vs your average price; shorts count a rise as down; "none" when empty | `::test_q2_positions_down_more_than_5pct` |
| "What did I pay on average for INFY?" | `get_average_price` | holding average and today's intraday averages reported separately; says plainly when not held | `::test_q3_average_price` |
| "Show NIFTY options near the money for this expiry." | `option_chain_near_atm` | nearest expiry on or after today; ATM ± N strikes from the 021 index price; LTP, OI, IV, delta from 021 `oc` mode | `::test_q4_nifty_options_near_the_money` |
| "Which stocks in my portfolio are oversold?" | `screen_portfolio` | RSI(14), Wilder smoothing, closed daily bars, oversold < 30; value and data date per symbol; skipped symbols with the reason | `::test_q5_oversold_screen_with_yfinance_off` |
| "Is INFY above its 200-day average? What's its MACD saying?" | `get_technicals` | SMA50/SMA200/MACD(12,26,9) on closed daily bars, with bar count; refuses on short history; flags analysis-vs-021 gaps above 1%; no advice | `::test_technicals_report_bars_and_never_advise` |
| Ambiguous names ("HDFC") | all | asks, listing candidates | `::test_ambiguous_symbol_asks_with_candidates` |

These tests run while the fake 021 injects 500, 503 and 429 errors (plus 30% random failures) and yfinance is switched off.

## L2 orders with confirmation

| Request | What Kraken does | Test |
|---|---|---|
| "Buy 10 Reliance at market" | Card: NSE · RELIANCE · BUY 10 · MARKET · CNC, 021 reference price and estimated value; payload `price: 0` | `tests/unit/test_order_builder.py::test_market_buy_defaults_to_cnc_with_reference_price` |
| "Buy Reliance" (no quantity) | Asks how many; never defaults | `::test_missing_quantity_is_asked_never_defaulted` |
| "Sell half my TCS" (7 held) | 3, with "rounded down" stated; half of 1 is refused; asks when both a holding and an intraday position exist | `::test_sell_half_of_seven_is_three_with_rounding_stated`, `::test_sell_half_of_one_is_refused`, `::test_holding_and_intraday_position_both_present_asks_which` |
| "₹2,800.05", "2.8k" | Parsed to paise by code; rounded to the tick in the trader's favour (buy down, sell up) with a notice; outside today's circuit → refused | `::test_limit_price_text_is_parsed_and_rounded_in_traders_favour`, `::test_price_outside_circuit_refused` |
| "Buy 2 lots NIFTY 24500 CE" | Units = lots × lot size (card shows both); nearest expiry on or after today, stated; NRML; lot multiple and freeze limit enforced | `::test_option_lots_to_units_and_nearest_expiry`, `::test_fo_units_not_lot_multiple_refused_and_freeze_limit` |
| Stop-loss | Buy: trigger above LTP, price ≥ trigger; sell: the reverse, checked against the live 021 price | `::test_stop_loss_rules_checked_against_ltp` |
| "Buy NIFTY" | Refused (indices are data only), futures/options offered | `::test_index_is_refused_with_alternative` |
| Selling more than held | Refused on CNC; opening a short needs the explicit word "short" (INTRADAY) | `::test_selling_more_than_held_on_cnc_refused_and_short_needs_explicit_word` |
| Market closed | Becomes an after-market order (AMO), labelled on the card | `::test_market_closed_becomes_labelled_amo` |
| "Move my stop-loss on HDFC Bank up to 1640" | Finds the single open SL order; proposes a modify with its full new state; keeps the limit valid for the new trigger | `::test_move_stop_loss_up_builds_full_new_state`, `::test_moving_buy_stop_loss_keeps_limit_valid` |
| Zero or several matching orders; filled order | Refuses / asks with a list; "only pending orders can be modified" | `::test_modify_with_two_matching_orders_asks_and_none_refuses`, `::test_filled_order_cannot_be_modified` |
| "Cancel my Infosys buy" | Cancel card for that order; refused at approval if it filled meanwhile | `::test_cancel_by_description`, `test_execution.py::test_order_filled_before_cancel_approval_is_refused` |

**Phase 2 exit test:** `tests/unit/test_l2_exit.py` runs 200 order runs, each with a concurrent double approval, while the fake 021 injects timeouts after booking, timeouts before booking, 503s and risk rejections on 40% of order POSTs, plus 10% random errors on every call. It asserts:
- zero duplicate orders;
- every payload 021 received is byte-for-byte the approved one (same SHA-256);
- the journal says ACKED exactly when 021 booked the order;
- nothing is left unresolved.

## Failure handling

| Scenario | Behaviour | Test |
|---|---|---|
| 500 / 503 / 429 on a read | Retry with exponential backoff and full jitter, at most 3 times, then an honest error | `tests/unit/test_broker_rest_client.py::test_get_retries_transient_errors_then_succeeds`, `::test_get_gives_up_after_max_retries_with_honest_error` |
| 429 with `Retry-After` | Waits at least that long and pauses the shared rate limiter | `::test_429_honours_retry_after`, `tests/unit/test_rate_limiter.py` |
| HTML gateway error or read timeout on a GET | Retried like a 503 | `::test_html_gateway_error_on_get_is_retried`, `::test_read_timeout_on_get_is_retried` |
| Token revoked by another login, or expired | One single-flight re-login; the read is replayed once | `::test_revoked_token_triggers_single_relogin_and_read_is_replayed` |
| Order POST times out (booked or not), or gets a 503 | Journal state UNKNOWN; **never resent**; the reconciler matches `GET /orders` → ACKED, NOT_PLACED, or AMBIGUOUS (never auto-resolved) | `tests/unit/test_execution.py::test_timeout_after_accept_is_unknown_then_reconciled_never_resent`, `tests/unit/test_reconciler_tracker.py::test_unknown_not_booked_becomes_not_placed_after_all_attempts`, `::test_two_identical_unlinked_orders_are_ambiguous_never_resent` |
| Token revoked at the moment of sending (another login with the same UCC) | 401 → not sent, never replayed; the session is renewed and a fresh card is offered for a new click | `test_execution.py::test_token_revoked_at_send_is_not_sent_and_offers_a_fresh_card` |
| Gemini rate limit (429) or overload (500/503) | 429: "wait about a minute"; 500/503: one quick retry, then an honest error. The real HTTP code is logged | `tests/unit/test_gemini_adapter.py` |
| A 021 order already linked to one approval | Never counted for another | `test_reconciler_tracker.py::test_already_linked_order_is_not_reused` |
| Server killed between approval and send | On boot, SENDING rows are reconciled from the order book before anything else; recovery never sends | `test_reconciler_tracker.py::test_boot_recovery_reconciles_rows_left_sending` |
| Order appears in 021 after being marked NOT_PLACED | Linked when its event arrives, and reported | `test_reconciler_tracker.py::test_late_order_after_not_placed_is_linked_and_reported` |
| HTTP 500 with an error text on an order action | Shown as a rejection with 021's reason | `test_execution.py::test_risk_rejection_is_recorded_with_reason` |
| Connection never opened / 401 on an order action | NOT_SENT; the trader is told it was not sent | `test_execution.py::test_connect_error_is_not_sent`, `test_broker_rest_client.py::test_order_after_token_revocation_is_not_sent_and_session_renewed` |
| Accepted by REST, rejected on the orders socket | Card updates to Rejected with the reason (REST is re-read as the source of truth) | `test_reconciler_tracker.py::test_rejection_reason_from_socket_and_other_ucc_ignored` |
| Fills while the orders socket was down | REST catch-up after reconnect | `test_reconciler_tracker.py::test_catch_up_after_reconnect_uses_rest` |
| Cancel sent but the order filled first | Reported as "filled before the cancel arrived" | `test_reconciler_tracker.py::test_unknown_cancel_where_order_filled_first` |
| 403 / 421 / 422 | Typed configuration/safety errors, never retried | `test_broker_rest_client.py::test_configuration_errors_are_typed_and_not_retried` |
| Market socket dropped (including the 08:00 IST restart) | Reconnect with backoff, fresh key, resubscribe everything | `tests/unit/test_market_socket.py::test_reconnects_with_new_key_and_resubscribes` |
| Stale price (old connection, or socket silent > 30 s) | Flagged in answers; market orders and approvals refuse without a fresh 021 price | `test_market_socket.py::test_quote_is_stale_until_refreshed_on_new_connection`, `test_order_builder.py::test_no_live_price_refuses_market_order` |
| Subscription silently ignored by 021 | Watchdog re-sends twice, then marks it silent | `test_market_socket.py::test_watchdog_resends_silent_subscription_then_marks_it_silent` |
| 100-instrument cap | Holdings/positions pinned; ad-hoc subscriptions evicted LRU | `test_market_socket.py::test_instrument_cap_evicts_unpinned_lru_and_never_pinned` |
| Binary frames: several packets, snapshot extras, heartbeats, per-exchange layouts, order events | Parsed by transaction code; unknown codes stop parsing and are reported | `tests/unit/test_market_packets.py` |
| yfinance down or empty; fewer than 15 bars; today's bar still forming | Stored candles marked stale / "not enough data" with bar count / excluded and reported | `tests/unit/test_candle_service.py`, `test_l1_read_tools.py::test_q5_oversold_screen_with_yfinance_off` |
| Gemini unavailable or key missing | The chat reply says so; no fabricated answer | `test_chat_service.py::test_llm_outage_is_reported` |

## Data sources

- **021 Trade sandbox:** positions, holdings, trades, orders, instruments, live prices and the option chain. Every order, price check and P&L figure comes from here.
- **yfinance / NSE (analysis only):** adjusted daily history for indicators, and the option-chain side panel inherited from the earlier codebase. This data may be delayed and can differ from the sandbox's simulated prices. It never goes into an order.

## Architecture

```
web chat ─/v1/chat─▶ CopilotChatService ─▶ Gemini (read tools + draft tools; no send tool)
                          │
              read tools ─┤─ draft tools ─▶ OrderBuilder (deterministic) ─▶ ProposalService ─▶ proposals (60 s, hash)
                          │
UI card ─ Approve ─▶ POST /v1/proposals/{id}/approve ─▶ ExecutionService ─▶ TradeRestClient ─▶ 021 (one attempt)
                                                            │ journal: ACKED | REJECTED | NOT_SENT | UNKNOWN
                                                            └─▶ Reconciler (GET /orders) · OrderTracker ◀─ orders socket
                                                                         └─▶ UserHub ─▶ WS /v1/stream/orders
```

### Web UI

Sign in at `/login.html` (Supabase). The dashboard opens on the **Copilot** tab ([frontend/copilot.js](frontend/copilot.js), [frontend/kraken-api.js](frontend/kraken-api.js)); the inherited Option Chain and Technicals tabs are still there.

| What the trader sees | How |
|---|---|
| Chat with tool chips and expandable data tables | `POST /v1/chat`; tables are built from `data[].result`, never parsed from the reply |
| An order card for each proposal, with a 60 s countdown, AMO badge and every notice | Rendered only from `GET /v1/proposals/{id}`; Approve echoes that card's `payload_hash` |
| Approve outcomes: sent, rejected (021's reason), not sent, checking (unknown), re-quote (fresh card), expired | Approve response `status` / HTTP code ([docs/API.md](docs/API.md#post-v1proposalsidapprove)) |
| Order journal with Kraken state and 021 status, updated live | `WS /v1/stream/orders` (JWT in the first message); polls `GET /v1/orders` every 10 s while the socket is down |
| Health pills (021, instruments, feed, AI, orders, kill switch); Approve hidden when orders are off | `GET /v1/copilot/status` every 30 s |

All server text is rendered with `textContent`, and the token goes only in the `Authorization` header (never a cookie). The UI has no automated tests yet. It was checked by hand in a browser against the fake 021: card → Approve → order sent → live fill; Reject; a "sell half" card with its rounding notice; a refusal when no fresh price is available.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for diagrams of every flow. Key points:
- `domains/broker` is the only code that talks to 021.
- Exactly one uvicorn worker runs, because 021 allows one live token per account ([docker/supervisord.conf](docker/supervisord.conf)).
- Order features need the Postgres order tables. Without them they stay off; there is no in-memory fallback in production ([app/runtime.py](app/runtime.py)).
- Celery runs analysis jobs only and never talks to 021.

## Security

| Measure | Code | Test |
|---|---|---|
| Supabase JWTs verified server-side (signature, expiry, audience, subject); fails closed | [shared/auth/supabase_jwt.py](shared/auth/supabase_jwt.py) | `tests/unit/test_auth.py` |
| Every chat, proposal, order and stream route requires a verified login; users see only their own proposals and orders | [copilot router](domains/copilot/api/router.py), [orders router](domains/orders/api/router.py) | `test_auth.py::test_chat_requires_login`, `test_orders_api.py::test_other_users_cannot_see_or_approve` |
| Approve/reject accept only `application/json` and refuse foreign `Origin`s; no CSRF token is needed because auth is a Bearer header, never a cookie (ADR-011) | [orders router](domains/orders/api/router.py) | `test_orders_api.py::test_approve_requires_login_json_and_allowed_origin` |
| Order stream: Origin checked on handshake; first message must be a valid JWT | [orders router](domains/orders/api/router.py) | `test_orders_api.py::test_stream_requires_auth_and_pushes_updates` |
| Tokens, passwords, access tokens and `token=` values are redacted from logs | [shared/logging/redaction.py](shared/logging/redaction.py) | `tests/unit/test_redaction.py` |
| Tests never read `.env` and cannot log in to the real 021 account | [tests/conftest.py](tests/conftest.py), [app/config/testing.py](app/config/testing.py) | the whole suite runs offline |
| Postgres and Redis are not published to the host; Redis requires a password; the DB user is not a superuser | [docker-compose.yml](docker-compose.yml), [docker/start.sh](docker/start.sh) | configuration |
| CI: ruff, unit tests, gitleaks on full history; pip-audit reported but not yet blocking | [.github/workflows/ci.yml](.github/workflows/ci.yml) | CI |

## Running locally

1. Configure the environment:
   ```bash
   cp .env.example .env
   ```
   Fill in `TRADE_API_USERNAME` (your UCC, e.g. `HACK1234`, not your email), `TRADE_API_PASSWORD`, `GEMINI_API_KEY`, `REDIS_PASSWORD` (also inside `REDIS_URL`), `DB_PASSWORD` (also inside `DATABASE_URL`), and the Supabase values. See [docs/RUNBOOK.md](docs/RUNBOOK.md#environment-variables).
2. Start the stack (app on http://127.0.0.1:8000):
   ```bash
   docker compose up -d --build
   ```
   On an existing database volume, apply new migrations (required for orders):
   ```bash
   docker compose exec app python scripts/migrate.py
   ```
   Then open http://127.0.0.1:8000/login.html, sign in, and use the **Copilot** tab. Open the app at an address listed in `ALLOWED_ORIGINS` (by default `http://127.0.0.1:8000` and `http://localhost:8000`); otherwise Approve returns 403 and live order updates are refused.
3. Optional: a read-only check against the real sandbox. It logs in with your UCC, which revokes the token of any running Kraken that uses the same account:
   ```bash
   python scripts/smoke_021.py
   ```
4. Run the tests and lint:
   ```bash
   pip install -r requirements-dev.txt
   pytest tests/unit -q
   ruff check .
   ```

## Documentation

| Doc | What's in it |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Components, process model, request and order flows, 021 gateway, market data, contracts (with diagrams) |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Architecture decision records (why the LLM can't send, one worker, no order retries, no CSRF token, …) |
| [docs/SECURITY.md](docs/SECURITY.md) | Threat model and controls, each marked built or planned |
| [docs/API.md](docs/API.md) | Chat, proposal, order and stream API contract for the UI |
| [docs/RUNBOOK.md](docs/RUNBOOK.md) | Environment variables, start-up, health checks, troubleshooting |
| [docs/TESTING.md](docs/TESTING.md) | Fake 021 and fault injection, coverage map, phase exit criteria |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Phases 3–5, owners and team seams |
| [docs/PHASE2_PLAN.md](docs/PHASE2_PLAN.md) | Level 2 design: flow, pieces, builder rules, journal states |

## Known limitations

- 021 has no funds endpoint. Kraken enforces a per-order value limit (`MAX_ORDER_VALUE_PAISE`) and shows 021's own risk rejection (for example insufficient funds) with its reason; it does not compute margin.
- Exchange holidays are not modelled. On a holiday, a normal order is sent as non-AMO and 021's rejection is shown.
- 021 documents the instruments `expiry` field only as "an integer timestamp from the exchange". Kraken detects the encoding ([instruments.py](domains/broker/infrastructure/instruments.py)). Verify with `scripts/smoke_021.py`.
- Modifying a partially filled order is refused (cancel the rest and place a new order instead).
- An UNKNOWN order is matched on token, qty, price, product and time sent, because 021 has no client order ID. If two identical orders could match, it is marked AMBIGUOUS for the trader to check and is never resent.
- Realized P&L covers round trips made today; carried-forward closes are not counted, and the answer says so.
- Chat history and per-user rate limits are in memory (one worker), so they reset on restart. Proposals and the order journal are in Postgres.
- The inherited alert rules (`/v1/notifications`) require a verified login but have no producer feeding them; they are rebuilt in Level 3.
- The inherited multi-day research export button is hidden, because its backend route was removed with the Black-Scholes code.

## Future scope

Not built yet, in planned order:

- **L3: standing instructions.** Persisted conditions with an atomic claim (fire once), crash recovery, holding-drop alerts, indicator conditions.
- **L4: multi-step plans.** Exiting losing intraday positions, rebalancing to a 20% maximum weight, one approval, paced execution, per-leg reports.
- Streaming chat responses, an audit-log viewer in the UI, a NL eval set and a prompt-injection red-team set (Phase 5).
