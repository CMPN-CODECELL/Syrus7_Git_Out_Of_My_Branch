# Kraken

Kraken is an AI trading copilot for the 021 Trade Developer Sandbox (021 Trade Hackathon, problem 021-01 "Copilot, Not Autopilot"). A trader asks questions about their 021 account in plain English through a web chat.

**Current scope: Level 1, read-only.** Kraken answers questions about P&L, positions, average prices, option chains and technical indicators. It cannot place, modify or cancel orders: no code path in this repository sends an order to 021 on a user's behalf. Levels 2–4 are listed under [Future scope](#future-scope).

Every claim below links to the code that implements it and the test that checks it. If a capability is not in these tables, it is not built.

## Safety design (as built)

| Claim | Code | Test |
|---|---|---|
| The LLM only has read-only tools; none can create, send, modify or cancel an order | [tool_specs.py](domains/copilot/domain/tool_specs.py) | `tests/unit/test_chat_service.py::test_no_tool_can_touch_orders` |
| Tool calls are validated against strict schemas; unknown tools and extra arguments are refused | [chat_service.py](domains/copilot/application/chat_service.py) | `test_chat_service.py::test_unknown_tool_is_refused`, `::test_invalid_and_extra_arguments_are_refused` |
| Tool results reach the LLM wrapped as `untrusted_data` with an instruction never to follow text inside them | [chat_service.py](domains/copilot/application/chat_service.py), [prompts.py](domains/copilot/application/prompts.py) | `test_chat_service.py::test_tool_results_are_fenced_as_untrusted_data` |
| Third-party symbol text is reduced to a safe charset and at most 24 chars before the LLM sees it | [read_tools.py](domains/copilot/application/read_tools.py) (`safe_symbol`) | `tests/unit/test_l1_read_tools.py::test_injected_symbol_text_is_neutralised` |
| A reply that claims an order was placed/sent/cancelled is replaced with a factual message | [chat_service.py](domains/copilot/application/chat_service.py) | `test_chat_service.py::test_replies_claiming_an_order_action_are_replaced` |
| Numbers come from tools (021 data, Kraken's indicator engine), returned to the UI as structured `data` next to the text | [chat_service.py](domains/copilot/application/chat_service.py) | `test_chat_service.py::test_tool_results_are_fenced_as_untrusted_data` |
| Order contracts for later levels: exact 021 payload, SHA-256 of the canonical payload, hash-checked proposals and plans, no default quantity | [shared/contracts/](shared/contracts/) | `tests/unit/test_contracts.py` |

## L1 questions Kraken answers

All portfolio and price data comes from 021. Prices are integer paise internally and are shown as ₹.

| Question | Tool | Definition reported with the answer | Test |
|---|---|---|---|
| "What's my P&L today?" | `get_pnl` | unrealized = (LTP − average price) × open qty; realized = today's matched buy/sell trades; holdings P&L and day change vs previous close | `test_l1_read_tools.py::test_q1_pnl_today` |
| "Which positions are down more than 5%?" | `filter_positions` | move vs your average price; shorts count a rise as down; "none" when empty | `::test_q2_positions_down_more_than_5pct` |
| "What did I pay on average for INFY?" | `get_average_price` | holding average and today's intraday averages reported separately; says plainly when not held | `::test_q3_average_price` |
| "Show NIFTY options near the money for this expiry." | `option_chain_near_atm` | nearest expiry on or after today; ATM ± N strikes from the 021 index price; LTP, OI, IV, delta from 021 `oc` mode | `::test_q4_nifty_options_near_the_money` |
| "Which stocks in my portfolio are oversold?" | `screen_portfolio` | RSI(14), Wilder smoothing, closed daily bars, oversold < 30; lists value and data date per symbol; lists skipped symbols with the reason | `::test_q5_oversold_screen_with_yfinance_off` |
| "Is INFY above its 200-day average? What's its MACD saying?" | `get_technicals` | SMA50/SMA200/MACD(12,26,9) on closed daily bars, with bar count; refuses when history is too short; flags analysis-vs-021 price gaps above 1%; no buy/sell advice | `::test_technicals_report_bars_and_never_advise` |
| Ambiguous names ("HDFC") | all | asks, listing candidates | `::test_ambiguous_symbol_asks_with_candidates` |

These tests run while the fake 021 injects 500, 503 and 429 errors (plus 30% random failures) and yfinance is switched off.

## Failure handling

| Scenario | Behaviour | Test |
|---|---|---|
| 500 / 503 / 429 on a read | Retry with exponential backoff and full jitter, at most `TRADE_API_MAX_GET_RETRIES` (3) times, then an honest error | `tests/unit/test_broker_rest_client.py::test_get_retries_transient_errors_then_succeeds`, `::test_get_gives_up_after_max_retries_with_honest_error` |
| 429 with `Retry-After` | Waits at least that long and pauses the shared rate limiter for every caller | `::test_429_honours_retry_after`, `tests/unit/test_rate_limiter.py` |
| HTML gateway error or read timeout on a GET | Retried like a 503 | `::test_html_gateway_error_on_get_is_retried`, `::test_read_timeout_on_get_is_retried` |
| Token revoked by another login, or expired | One single-flight re-login shared by all concurrent callers; the read is replayed once | `::test_revoked_token_triggers_single_relogin_and_read_is_replayed`, `::test_concurrent_reads_share_one_login` |
| Order POST times out after 021 accepted it | `BrokerOutcomeUnknownError`; never resent (exactly one POST) | `::test_order_post_timeout_after_accept_is_outcome_unknown_and_not_resent` |
| Order POST gets 503 | Outcome unknown, not retried | `::test_order_post_503_is_outcome_unknown_not_retried` |
| HTTP 500 with an error text on an order action | Shown as a rejection with 021's reason, not as an outage | `::test_order_risk_rejection_500_is_shown_as_rejection` |
| 401 on an order action | Session renewed; the order is reported as NOT sent and not replayed | `::test_order_after_token_revocation_is_not_sent_and_session_renewed` |
| 403 / 421 / 422 | Typed configuration/safety errors, never retried | `::test_configuration_errors_are_typed_and_not_retried` |
| Market socket dropped (including the 08:00 IST restart) | Reconnect with backoff, fresh ephemeral key, resubscribe everything | `tests/unit/test_market_socket.py::test_reconnects_with_new_key_and_resubscribes` |
| Price from a previous connection, or socket silent > 30 s | Quote flagged stale; answers carry stale warnings | `test_market_socket.py::test_quote_is_stale_until_refreshed_on_new_connection` |
| Subscription silently ignored by 021 | Watchdog re-sends twice, then marks it silent | `test_market_socket.py::test_watchdog_resends_silent_subscription_then_marks_it_silent` |
| 100-instrument cap | Holdings/positions are pinned; ad-hoc subscriptions are evicted least-recently-used | `test_market_socket.py::test_instrument_cap_evicts_unpinned_lru_and_never_pinned` |
| Several packets per frame, snapshot extra bytes, heartbeats, per-exchange full layouts | Parser walks packets by transaction code; unknown codes stop parsing and are reported | `tests/unit/test_market_packets.py` |
| yfinance down or empty | Serves stored candles marked stale; without them, says no data | `tests/unit/test_candle_service.py::test_yfinance_down_serves_cache_marked_stale`, `::test_no_cache_no_live_is_reported` |
| Fewer than 15 daily bars | "not enough data for RSI(14)" with the bar count; never computed on a short series | `test_l1_read_tools.py::test_q5_oversold_screen_with_yfinance_off`, `tests/unit/test_analytics_domain.py::test_rsi_refuses_short_series` |
| Today's daily bar still forming | Excluded from indicators during market hours, and reported | `test_candle_service.py::test_todays_forming_bar_is_excluded_during_session` |
| Gemini unavailable or key missing | The chat reply says so; no fabricated answer | `test_chat_service.py::test_llm_outage_is_reported`, `tests/unit/test_auth.py::test_chat_without_llm_key_reports_unavailable` |

## Data sources

- **021 Trade sandbox:** positions, holdings, trades, instruments, live prices and the option chain. Anything that becomes a P&L figure or a price comes from here.
- **yfinance / NSE (analysis only):** adjusted daily history for indicators, and the option-chain side panel inherited from the earlier codebase. This data may be delayed and can differ from the sandbox's simulated prices. `get_technicals` reports the gap when it exceeds 1%.

## Architecture

```
web chat ──/v1/chat──▶ CopilotChatService ──▶ Gemini (read-only tool declarations)
                              │
                              ▼ validated tool calls
                         ReadToolbox ──▶ TradeRestClient ──▶ 021 REST   (token manager, rate limiter, GET retries)
                              │     └──▶ PriceCache ◀── MarketSocketClient ◀── 021 market websocket (binary)
                              │     └──▶ InstrumentStore (daily 021 instruments CSV, disk cached)
                              └──────▶ CandleService ──▶ Timescale OhlcCandles ◀── Celery daily backfill (yfinance)
```

- `domains/broker`: the only code that talks to 021 ([rest_client.py](domains/broker/infrastructure/rest_client.py), [token_manager.py](domains/broker/infrastructure/token_manager.py), [errors.py](domains/broker/domain/errors.py), [instruments.py](domains/broker/infrastructure/instruments.py)).
- `domains/marketdata`: binary packet parsers, price cache, socket client, symbol map ([packets.py](domains/marketdata/domain/packets.py), [market_socket.py](domains/marketdata/infrastructure/market_socket.py)).
- `domains/copilot`: tools, chat orchestration and the Gemini adapter.
- `domains/historical`: daily candles and the backfill job ([candle_service.py](domains/historical/application/candle_service.py), [tasks.py](domains/historical/tasks.py)).
- [app/runtime.py](app/runtime.py) wires everything inside the single uvicorn worker. It refreshes instruments daily, keeps holdings and positions subscribed, and publishes the analysis watchlist for Celery. Tests: `tests/unit/test_runtime.py`.
- Exactly one uvicorn worker runs ([docker/supervisord.conf](docker/supervisord.conf)), because 021 allows one live token per account and a second worker would revoke the first worker's token.
- Celery runs analysis jobs only and never talks to 021 ([app/config/celery.py](app/config/celery.py)).

## Security

| Measure | Code | Test |
|---|---|---|
| Supabase JWTs verified server-side (signature, expiry, audience, subject; HS256 secret or project JWKS; fails closed) | [shared/auth/supabase_jwt.py](shared/auth/supabase_jwt.py), [shared/middleware/auth.py](shared/middleware/auth.py) | `tests/unit/test_auth.py` |
| `/v1/chat` and `/v1/copilot/status` require a verified login; chat is rate-limited per user and capped in length | [domains/copilot/api/router.py](domains/copilot/api/router.py) | `test_auth.py::test_chat_requires_login` |
| Tokens, passwords, access tokens and `token=` values are redacted from logs | [shared/logging/redaction.py](shared/logging/redaction.py) | `tests/unit/test_redaction.py` |
| The 021 password stays inside the token manager and never appears in reprs | [token_manager.py](domains/broker/infrastructure/token_manager.py) | `test_broker_rest_client.py::test_password_never_in_repr` |
| Tests never read `.env` and cannot log in to the real 021 account | [tests/conftest.py](tests/conftest.py), [app/config/testing.py](app/config/testing.py) | the whole suite runs offline |
| Postgres and Redis are not published to the host; Redis requires a password; the DB user is not a superuser | [docker-compose.yml](docker-compose.yml), [docker/supervisord.conf](docker/supervisord.conf), [docker/start.sh](docker/start.sh) | configuration |
| Error responses carry a request ID, never a stack trace | [app/main.py](app/main.py) | none yet |
| CI: ruff, unit tests, gitleaks on full history; pip-audit reported but not yet blocking | [.github/workflows/ci.yml](.github/workflows/ci.yml), [.pre-commit-config.yaml](.pre-commit-config.yaml) | CI |

## Running locally

1. Configure the environment:
   ```bash
   cp .env.example .env
   ```
   Fill in `TRADE_API_USERNAME` (your UCC, e.g. `HACK1234`, not your email), `TRADE_API_PASSWORD`, `GEMINI_API_KEY`, `REDIS_PASSWORD` (also inside `REDIS_URL`), `DB_PASSWORD` (also inside `DATABASE_URL`), and the Supabase values.
2. Start the stack (app on http://127.0.0.1:8000):
   ```bash
   docker compose up -d --build
   ```
   On an existing database volume, apply new migrations with `docker compose exec app python scripts/migrate.py`.
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

The chat API contract for the UI is in [docs/API.md](docs/API.md).

## Known limitations

- Exchange holidays are not modelled. "Last closed session" only skips weekends, and the staleness checks allow a 4-day tolerance.
- 021 documents the instruments `expiry` field only as "an integer timestamp from the exchange". Kraken detects YYYYMMDD, Unix seconds or milliseconds, and seconds since 1980 ([instruments.py](domains/broker/infrastructure/instruments.py)). Verify against real data with `scripts/smoke_021.py`.
- Realized P&L covers round trips made today. Closing quantity carried forward from earlier days is not counted, and the answer says so.
- Chat history and the per-user rate limiter are in memory (one worker), so they reset on restart.
- The inherited alert rules (`/v1/notifications`) now require a verified login, but have no producer feeding them. They are rebuilt in Level 3.
- The analysis side-panel endpoints (`/v1/derivatives/{symbol}`, `/v1/derivatives/{symbol}/technicals`, `/v1/pricer/ticker/{symbol}`) come from the earlier codebase and use yfinance/NSE data.

## Future scope

Not built yet, in planned order:

- **L2: orders with confirmation.** Intent → draft → deterministic validator (tick, circuits, lot size, freeze qty, product/exchange, SL rules, funds) → server-side proposal card → one-time, hash-bound, expiring approval → place/modify/cancel. Includes an order journal, a reconciler for UNKNOWN outcomes via `GET /orders`, the orders socket client (its parser already exists and is tested in `test_market_packets.py`), price-drift re-quotes, and CSRF protection on approve.
- **L3: standing instructions.** Persisted conditions with an atomic claim (fire once), crash recovery, holding-drop alerts, and indicator conditions.
- **L4: multi-step plans.** Exiting losing intraday positions, rebalancing to a 20% maximum weight, one approval, paced execution, and per-leg reports.
- Append-only audit table in Postgres (the REST client already exposes an audit hook), streaming chat responses, and moving the side-panel technicals onto the Timescale store.
