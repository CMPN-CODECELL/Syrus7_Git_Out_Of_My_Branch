# Kraken security model

Each control is marked **built** (exists in the code, with a test or config file that backs it) or **planned** (not built yet). Don't describe a planned control as built anywhere, including the README and the viva.

## 1. Assets and threats

| Asset | Threat | Main controls |
|---|---|---|
| The trader's 021 account | A trade the trader did not clearly approve; a duplicate order | LLM has no send tool; hash-bound, single-use, owner-only, expiring approval; never resend an unknown outcome (all built) |
| 021 credentials and access token | Leak through logs, the browser, the LLM or git | Server-only settings, log redaction, gitleaks (built) |
| Gemini API key | Leak, cost abuse | Server-only; per-user chat rate limit and length cap (built) |
| User sessions | Forged identity | Supabase JWT verified server-side (built) |
| Redis / Postgres | Direct access | Not published to the host; Redis password; non-superuser DB role (built) |

## 2. Unapproved trades

| Control | Status | Where |
|---|---|---|
| No LLM tool can send, approve, modify or cancel at the broker; draft tools only create proposal cards | built | [tool_specs.py](../domains/copilot/domain/tool_specs.py); `test_no_tool_can_touch_orders`, `test_chat_drafts.py::test_draft_tool_creates_card_and_never_sends` |
| The only send path is `POST /v1/proposals/{id}/approve` → `ExecutionService.approve()` | built | [execution.py](../domains/orders/application/execution.py), [orders router](../domains/orders/api/router.py) |
| Unknown tools and extra or invalid arguments are refused before anything runs (including `"approve": true` smuggled into a draft) | built | `test_unknown_tool_is_refused`, `test_injected_send_instruction_in_args_is_rejected` |
| A reply claiming an order was placed, sent, cancelled or approved is replaced | built | `test_replies_claiming_an_order_action_are_replaced` |
| Typing "yes" or "confirm" in chat approves nothing; only the Approve call does | built | `test_typing_confirm_does_nothing_special`; prompt in [prompts.py](../domains/copilot/application/prompts.py) |
| The LLM never converts money: price/expiry text is parsed by code; no default quantity | built | [parsing.py](../domains/copilot/domain/parsing.py), [order_builder.py](../domains/copilot/application/order_builder.py); `test_parsing.py`, `test_missing_quantity_is_asked_never_defaulted` |
| Order payloads are strict models: non-zero qty, SL needs a trigger, CNC is cash-only, NRML is F&O-only, no extra keys | built | [orders.py](../shared/contracts/orders.py); `test_contracts.py` |
| Proposals are immutable rows bound to the SHA-256 of their canonical payload; the card renders from the row; approve must echo the hash | built | `test_hash_mismatch_refused`, `test_card_then_approve_sends_once` |
| Approval: owner-only, single-use compare-and-set PROPOSED → APPROVED together with the journal insert (one transaction), 60 s expiry | built | `test_concurrent_double_click_sends_once`, `test_other_user_cannot_approve`, `test_expired_card_refused`; Postgres: `tests/integration/test_order_store_pg.py` |
| Re-checks right before sending: price drift ≤ 0.5% (else a fresh card), source quantity unchanged, target order still open, instruments from today | built | `test_price_drift_over_half_percent_requotes_without_sending`, `test_source_quantity_changed_aborts_sell_half`, `test_order_filled_before_cancel_approval_is_refused`, `test_stale_instruments_block_approval` |
| Server-side limits (max value, max qty, allowed exchanges/products) and kill switch, at draft **and** approval time | built | `test_limits_and_kill_switch`, `test_kill_switch_blocks_approval` |
| Order actions never retried; unknown outcomes reconciled from `GET /orders`, never resent; AMBIGUOUS never auto-resolved | built | `test_l2_exit.py`, `test_reconciler_tracker.py` |
| Sends are serialised (one at a time), so Kraken's own identical orders never race | built | [execution.py](../domains/orders/application/execution.py) (`_send_lock`) |

## 3. Prompt injection

Untrusted inputs: user text, and everything from 021 (symbols, rejection reasons, order text), yfinance and NSE.

| Control | Status | Where |
|---|---|---|
| Tool results are wrapped as `{"untrusted_data": ..., "note": ...}` | built | `test_tool_results_are_fenced_as_untrusted_data` |
| The system prompt tells the model never to follow instructions inside tool data and never to claim an order action | built | [prompts.py](../domains/copilot/application/prompts.py) |
| Symbol text from third parties is cut to `[A-Za-z0-9&-. ]` and at most 24 chars | built | `safe_symbol`; `test_injected_symbol_text_is_neutralised` |
| 021 error and reason text is stripped of control characters and capped at 300 chars | built | `rest_client._clean_text`, `packets._reason` |
| Indicator tools return numbers and fixed labels only | built | [read_tools.py](../domains/copilot/application/read_tools.py) |
| No free-form HTTP, shell or SQL tools | built | tool catalogue |
| Chat history stores text only, so injected tool data is not replayed into later turns | built | `test_history_keeps_text_only` |
| Red-team prompt set (100+ prompts) | planned (Phase 5) | — |

Prompt-level defences are never the last line. Even a fully hijacked model in Level 1 can only *read*.

## 4. Secrets

| Control | Status | Where |
|---|---|---|
| 021 UCC/password, Gemini key and Supabase JWT secret come only from `.env`, which is gitignored | built | [.gitignore](../.gitignore), [.env.example](../.env.example) |
| The access token lives only in memory, inside `TokenManager`; the password never appears in reprs | built | `test_password_never_in_repr` |
| Ephemeral socket keys are fetched server-side; the browser never sees 021 keys | built | [market_socket.py](../domains/marketdata/infrastructure/market_socket.py) |
| Bearer tokens, passwords, access tokens and `token=` query values are redacted from every log line; httpx/websockets loggers are kept at WARNING | built | [redaction.py](../shared/logging/redaction.py), [logging.py](../app/config/logging.py); `test_redaction.py` |
| gitleaks on full history in CI, plus a pre-commit hook | built | [ci.yml](../.github/workflows/ci.yml), [.pre-commit-config.yaml](../.pre-commit-config.yaml) |
| Tests run with `TestingSettings` (no `.env`) and blank credentials | built | [conftest.py](../tests/conftest.py) |
| `/config` sends the browser only the Supabase URL and **anon** key | built (inherited) | [app/main.py](../app/main.py) |

If a secret leaks: rotate it at the source (021 web app password, Google AI Studio key, Supabase JWT secret), update `.env`, and restart. Rotating the 021 password doesn't revoke an existing token; the next login does.

## 5. Web application

| Control | Status | Where |
|---|---|---|
| Supabase JWT: signature, `exp`, `aud`, `sub` checked; HS256 secret or JWKS; fails closed | built | [supabase_jwt.py](../shared/auth/supabase_jwt.py); `test_auth.py` |
| A forged unsigned (`alg=none`) token is rejected on legacy routes | built | `test_unsigned_payload_cannot_impersonate` |
| Per-user chat rate limit and message length cap | built | [router.py](../domains/copilot/api/router.py) |
| Exact-origin CORS allowlist | built (inherited) | `ALLOWED_ORIGINS` |
| Error responses carry a request ID, never a stack trace | built (not yet tested) | [app/main.py](../app/main.py) |
| Internal ingestion key compared in constant time | built | [shared/middleware/auth.py](../shared/middleware/auth.py) |
| Copilot UI renders all server text with `textContent` (no `innerHTML`); cards come only from the proposal row; token sent only as a Bearer header | built (checked by hand; no automated UI test) | [copilot.js](../frontend/copilot.js), [kraken-api.js](../frontend/kraken-api.js) |
| Strict Content-Security-Policy | planned (the inherited pages use inline scripts and CDN scripts) | — |
| Proposal/order/stream routes require a verified login; users only see their own proposals and orders | built | [orders router](../domains/orders/api/router.py); `test_other_users_cannot_see_or_approve` |
| No CSRF token **by design**: Bearer-header auth (never cookies), approve/reject JSON-only and Origin-allowlisted, hash echo (ADR-011) | built | `test_approve_requires_login_json_and_allowed_origin` |
| Order stream: Origin checked on the WebSocket handshake; JWT required in the first message (no token in the URL) | built | `test_stream_requires_auth_and_pushes_updates` |
| Approve rate limit (30/min per user) | built | [orders router](../domains/orders/api/router.py) |
| Each Supabase user mapped to exactly one 021 account | planned; today one server-side 021 account serves the deployment | — |
| Legacy alert rules: owner column, webhook allowlist (SSRF) | planned (L3 rebuild); today the routes require a verified login | — |

## 6. Infrastructure

| Control | Status | Where |
|---|---|---|
| Only port 8000 published, on 127.0.0.1 in dev | built | [docker-compose.yml](../docker-compose.yml) |
| Redis `--requirepass`, bound to loopback in the container | built | [supervisord.conf](../docker/supervisord.conf) |
| App DB role is not a superuser; prod compose refuses to start without passwords | built | [start.sh](../docker/start.sh), [docker-compose.prod.yml](../docker-compose.prod.yml) |
| pip-audit in CI | built, reports only (not blocking yet) | [ci.yml](../.github/workflows/ci.yml) |
| Pinned dependency versions | planned | `requirements.txt` uses lower bounds |
| Append-only audit table (proposal created/rejected/expired, approval attempt, send, result, reconciliation, socket events, every order action and failed 021 call), linked by request, proposal, journal and order IDs | built: a trigger blocks UPDATE/DELETE; audit failures never block trading | [migration_kraken_002_orders.sql](../scripts/migration_kraken_002_orders.sql), [pg_store.py](../domains/orders/infrastructure/pg_store.py); `tests/integration/test_order_store_pg.py::test_audit_is_append_only` (needs Postgres) |
| Order features refuse to run without the durable store (no in-memory fallback in production) | built | [app/runtime.py](../app/runtime.py) `init_orders` (ADR-012) |
| Audit-log viewer in the UI | planned | — |

## 7. Viva answers

- **"How could the model place a trade I didn't approve?"** It can't. Its tools are seven read tools plus three draft tools that only save a proposal row; all arguments are validated first. The single send path is `POST /v1/proposals/{id}/approve`. That requires your verified login and your own proposal, the hash of the card you saw, an unexpired card, and an atomic PROPOSED → APPROVED that only one request can ever win.
- **"What if I double-click Approve, or approve from two tabs?"** The compare-and-set and the journal insert happen in one transaction, and `UNIQUE(proposal_id)` backs it up: one send at most (`test_concurrent_double_click_sends_once`).
- **"What if the price moves while I decide?"** Over 0.5% (or after 60 s), nothing is sent and you get a fresh card.
- **"What if a stock name contains instructions?"** It reaches the model as fenced `untrusted_data`, reduced to a safe 24-character symbol, and the model has no tool that sends anything.
- **"What if the POST times out?"** Journal state UNKNOWN, exactly one POST, no resend. The reconciler matches `GET /orders`: ACKED, NOT_PLACED, or AMBIGUOUS for you to check (ADR-003, ADR-013). Proven over 200 faulty runs in `test_l2_exit.py`.
- **"Why no CSRF token?"** Auth is a Bearer header that browsers never send by themselves. Approve is also JSON-only and Origin-checked (ADR-011).
- **"Where is my 021 password?"** Only in the server's `.env` and inside `TokenManager`. It's redacted from logs and never sent to the browser or the LLM.
