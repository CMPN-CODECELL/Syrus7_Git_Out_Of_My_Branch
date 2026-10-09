# Kraken security model

Each control is marked **built** (exists in the code, with a test or config file that backs it) or **planned** (not built yet). Don't describe a planned control as built anywhere, including the README and the viva.

## 1. Assets and threats

| Asset | Threat | Main controls |
|---|---|---|
| The trader's 021 account | A trade the trader did not clearly approve | LLM has no send tool (built); hash-bound, single-use, expiring approval (planned, L2) |
| 021 credentials and access token | Leak through logs, the browser, the LLM or git | Server-only settings, log redaction, gitleaks (built) |
| Gemini API key | Leak, cost abuse | Server-only; per-user chat rate limit and length cap (built) |
| User sessions | Forged identity | Supabase JWT verified server-side (built) |
| Redis / Postgres | Direct access | Not published to the host; Redis password; non-superuser DB role (built) |

## 2. Unapproved trades

| Control | Status | Where |
|---|---|---|
| The LLM's tools are read-only; no tool can place, modify or cancel | built | [tool_specs.py](../domains/copilot/domain/tool_specs.py); `test_no_tool_can_touch_orders` |
| Unknown tools and extra or invalid arguments are refused before anything runs | built | [chat_service.py](../domains/copilot/application/chat_service.py); `test_unknown_tool_is_refused`, `test_invalid_and_extra_arguments_are_refused` |
| A reply claiming an order was placed, sent, cancelled or approved is replaced | built | `test_replies_claiming_an_order_action_are_replaced` |
| Typing "yes" or "confirm" in chat does nothing | built (no approval path exists) | `test_typing_confirm_does_nothing_special` |
| Order payloads are strict models: non-zero qty, SL needs a trigger, CNC is cash-only, NRML is F&O-only, no extra keys | built | [orders.py](../shared/contracts/orders.py); `test_contracts.py` |
| Proposals and plans are bound to the SHA-256 of their canonical payload | built (contracts only) | `test_proposal_rejects_hash_mismatch`, `test_plan_hash_covers_every_leg` |
| Approval endpoint: compare-and-set PROPOSED → APPROVED, hash match, 60 s TTL, 0.5% drift re-quote | planned (L2) | — |
| Server-side limits (max value, max qty, allowed exchanges/products) and kill switch | planned (L2): settings exist, enforcement does not | [settings.py](../app/config/settings.py) |
| Order actions never retried; lost responses reconciled, never resent | built (client); reconciler planned | `test_order_post_timeout_after_accept_is_outcome_unknown_and_not_resent` |

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
| UI renders with `textContent`, plus a strict CSP | planned (UI team) | [API.md](API.md) rendering rules |
| CSRF token on state-changing routes (especially approve) | planned (L2) | — |
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
| Append-only audit table (proposal, approval, request, response, socket event) | planned (L2); the REST client already has an audit hook | [rest_client.py](../domains/broker/infrastructure/rest_client.py) |

## 7. Viva answers

- **"How could the model place a trade I didn't approve?"** It can't. Its only tools are the seven read tools in `tool_specs.py`, and arguments are validated before anything runs. No route in the app sends an order today. From Level 2, sending requires `POST /proposals/{id}/approve` from an authenticated click, bound to the payload hash, used once and before expiry.
- **"What if a stock name contains instructions?"** It reaches the model as fenced `untrusted_data`, reduced to a safe 24-character symbol, and the model has no write tool to act on it anyway.
- **"What if the POST times out?"** `BrokerOutcomeUnknownError`, exactly one POST, no resend. It gets reconciled against `GET /orders` (ADR-003).
- **"Where is my 021 password?"** Only in the server's `.env` and inside `TokenManager`. It's redacted from logs and never sent to the browser or the LLM.
