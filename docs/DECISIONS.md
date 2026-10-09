# Architecture decision records

Short records of decisions that shape Kraken. Each one gives the context, the decision, and what follows from it. To change a decision, add a new record that supersedes the old one; don't edit history.

| ADR | Decision | Status |
|---|---|---|
| [001](#adr-001-the-llm-reads-and-drafts-it-never-sends) | The LLM reads and drafts; it never sends | Accepted |
| [002](#adr-002-one-uvicorn-worker-owns-the-021-session) | One uvicorn worker owns the 021 session | Accepted |
| [003](#adr-003-order-actions-are-never-retried) | Order actions are never retried | Accepted |
| [004](#adr-004-two-price-sources-021-for-money-yfinancense-for-analysis) | Two price sources: 021 for money, yfinance/NSE for analysis | Accepted |
| [005](#adr-005-integer-paise-end-to-end) | Integer paise end to end | Accepted |
| [006](#adr-006-gemini-behind-an-llm-port-manual-function-calling) | Gemini behind an LLM port, manual function calling | Accepted |
| [007](#adr-007-remove-black-scholes-pde-and-the-golden-zone-layer) | Remove Black-Scholes, PDE and the "Golden Zone" layer | Accepted |
| [008](#adr-008-staleness-is-per-connection-not-per-tick) | Staleness is per connection, not per tick | Accepted |
| [009](#adr-009-celery-never-talks-to-021) | Celery never talks to 021 | Accepted |
| [010](#adr-010-supabase-for-app-login-verified-server-side) | Supabase for app login, verified server-side | Accepted |

---

## ADR-001: The LLM reads and drafts; it never sends

**Context.** The challenge scores whether the copilot can ever cause a trade the trader did not clearly approve: misread requests, prompt injection through stock names or rejection reasons, and "yes" typed into chat.

**Decision.** The LLM gets read tools only (Level 1), and later read tools plus *draft* tools (Level 2+). Deterministic code turns a draft into an immutable server-side proposal bound to the SHA-256 of the exact payload. Only `POST /proposals/{id}/approve`, called by an authenticated human click, can send an order. Approval is single-use (compare-and-set) and expires.

**Consequences.** The safety argument fits in one sentence for the viva, and it's testable: `test_no_tool_can_touch_orders`. Chat text, including "confirm", can never approve anything. The confirmation card renders from the proposal row, never from LLM prose. As a further guard, a reply that claims an order action is replaced.

## ADR-002: One uvicorn worker owns the 021 session

**Context.** 021 allows one live token per account; logging in again revokes the previous token. Two workers or processes would keep revoking each other.

**Decision.** Run exactly one uvicorn worker ([supervisord.conf](../docker/supervisord.conf), [docker-compose.prod.yml](../docker-compose.prod.yml)). That worker owns the `TokenManager`, the market socket and (from Level 2) the execution service. Re-login is single-flight: concurrent 401s trigger one login.

**Consequences.** We scale by keeping the worker async, not by adding workers. Chat history and rate limiting can stay in memory for now. Scripts that log in (such as `scripts/smoke_021.py`) revoke the running app's token, and the app recovers on its next call. Each team member uses their own 021 account.

## ADR-003: Order actions are never retried

**Context.** The sandbox times out and returns 5xx on purpose. 021 has no client order ID, so a retried POST after a lost response can create a duplicate order.

**Decision.** Reads retry (at most 3 times, full-jitter backoff, honouring `Retry-After`). Order actions get exactly one attempt:
- A lost response, a 5xx other than a risk rejection, or a timeout raises `BrokerOutcomeUnknownError`. Level 2's reconciler resolves it through `GET /orders` and the orders socket, matching on token, qty, price, product and time sent.
- A 401 on an order action means 021 did not process it: re-login, report "not sent", don't replay.
- HTTP 500 with an error text is a risk rejection (`BrokerRejectedError`) and is shown with 021's reason.

**Consequences.** Some legitimate transient failures need the trader to approve again, which is the safe trade-off. Tested in `test_broker_rest_client.py` (`test_order_post_timeout_after_accept_is_outcome_unknown_and_not_resent` and its neighbours).

## ADR-004: Two price sources: 021 for money, yfinance/NSE for analysis

**Context.** The sandbox fills against its own simulated prices. Indicators need about a year of daily history, which 021 doesn't provide.

**Decision.** Anything that becomes an order, a P&L figure, a price trigger or a drift check uses 021. History and indicators use yfinance/NSE, stored in Timescale. When the two disagree by more than 1%, `get_technicals` says so. A yfinance price never goes into an order.

**Consequences.** We need a symbol map (021 ↔ NSE ↔ yfinance) and must report unmapped symbols as skipped. Indicator answers state their source and data date.

## ADR-005: Integer paise end to end

**Context.** 021 uses integer paise for prices, triggers, circuits, strikes and tick size. Floats cause rounding bugs and off-tick orders.

**Decision.** Every internal price is an `int` in paise, and the contracts enforce this. Rupee strings are produced only for display (`portfolio_math.rupees`). Quantity sign is the side.

**Consequences.** P&L math is exact and easy to test (`test_portfolio_math.py`). Tool results carry both display strings and `*_paise` integers.

## ADR-006: Gemini behind an LLM port, manual function calling

**Context.** The team chose Gemini. Tests must not call a real LLM, and a provider change on the day must be cheap.

**Decision.** The copilot depends on `LLMPort` ([ports.py](../domains/copilot/ports.py)). `GeminiLLM` implements it with the `google-genai` SDK, with automatic function calling **disabled**, so every tool call passes Kraken's argument validation. Tests use a scripted fake.

**Consequences.** Swapping providers means writing one adapter. Tool declarations use Gemini's schema dialect (uppercase types). Conversation history keeps text only; tool data is re-fetched rather than replayed.

## ADR-007: Remove Black-Scholes, PDE and the "Golden Zone" layer

**Context.** The inherited codebase priced options with BSM and a Crank-Nicolson PDE. An early prototype used them to turn the trader's order into a "Golden Zone" limit order. 021's `oc` mode already streams IV and greeks. The judging rules disqualify README claims the code doesn't back up.

**Decision.** Delete the BSM/PDE code, the research exporter, the Groww adapter and the Golden Zone reasoning layer. The copilot never changes the trader's requested order and gives no buy/sell advice.

**Consequences.** `POST /v1/pricer/calculate` and `GET /v1/export/research` are gone ([API.md](API.md#removed-endpoints)). `fair_priced_chain` in `/v1/derivatives/{symbol}` is always empty.

## ADR-008: Staleness is per connection, not per tick

**Context.** The market socket only sends instruments that changed, so an illiquid stock may not tick for minutes. Treating "no tick" as stale would make every illiquid holding look broken. Prices from before a reconnect are dangerous.

**Decision.** A quote is stale if the socket is down, no frame (including heartbeats) arrived for 30 s, or the quote is from a previous connection and hasn't been refreshed by the post-subscribe snapshot.

**Consequences.** Answers carry stale warnings that mean something. Level 3 triggers pause while the feed is unhealthy.

## ADR-009: Celery never talks to 021

**Context.** Celery workers are separate processes. A 021 login from one would revoke the app's token (ADR-002), and an order sent from a background job would bypass the approval path.

**Decision.** Celery runs analysis jobs only (option-chain snapshots, daily candle backfill). The app publishes the analysis watchlist to Redis (`kraken:analysis:watchlist`); Celery reads it. Level 3 standing-instruction firing runs inside the app worker.

**Consequences.** Backfill coverage follows the app's view of holdings and positions, with up to a 60 s delay.

## ADR-010: Supabase for app login, verified server-side

**Context.** The inherited middleware decoded JWTs without verifying them, so anyone could forge a user.

**Decision.** Keep Supabase as the login. The server verifies signature, expiry, audience and subject, using `SUPABASE_JWT_SECRET` (HS256) or the project's JWKS (ES256/RS256), and fails closed when neither is configured. Only the anon key reaches the browser.

**Consequences.** Every user-scoped route depends on `require_user`. Local development needs a real Supabase project or a JWT secret. Tests sign their own tokens with a test-only secret.
