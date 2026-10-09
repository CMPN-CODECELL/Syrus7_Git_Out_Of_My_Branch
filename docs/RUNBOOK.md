# Kraken runbook

How to configure, start, check and troubleshoot Kraken.

## Environment variables

Copy `.env.example` to `.env`. Write each line as `KEY=value`, with no spaces around `=` and no quotes (Docker Compose parses `.env` strictly).

| Variable | Required | Meaning |
|---|---|---|
| `APP_ENV` | no | `development` (default) or `production` |
| `ALLOWED_ORIGINS` | no | Comma-separated exact origins for CORS |
| `INTERNAL_API_KEY` | yes | Key for the internal `/v1/ingestion/*` routes |
| `REDIS_PASSWORD` | **yes** | Redis password inside the container; Redis won't start without it |
| `REDIS_URL` | yes | Must contain the password: `redis://:<REDIS_PASSWORD>@127.0.0.1:6379/0`, with special characters URL-encoded |
| `DB_USER`, `DB_PASSWORD` | yes | App database role. On an existing volume, keep the values it was created with |
| `DATABASE_URL` | yes | `postgresql://<DB_USER>:<DB_PASSWORD>@localhost:5432/NexusQuantDB` |
| `supabaseUrl`, `supabaseKey` | yes | Supabase project URL and **anon** key (never the service-role key) |
| `SUPABASE_JWT_SECRET` | one of these two | Legacy HS256 JWT secret. If empty, tokens are verified against `<supabaseUrl>/auth/v1/.well-known/jwks.json` |
| `SUPABASE_JWT_AUDIENCE` | no | Default `authenticated` |
| `TRADE_API_USERNAME` | yes for broker features | 021 UCC, e.g. `HACK1234` (not your email) |
| `TRADE_API_PASSWORD` | yes for broker features | Password chosen at 021 sign-up |
| `TRADE_API_BASE_URL`, `TRADE_WS_BASE_URL` | no | Default to the 021 dev sandbox |
| `TRADE_API_TIMEOUT_SECONDS` | no | Per-request timeout (default 10) |
| `TRADE_API_RATE_PER_SECOND` | no | Client-side rate limit (default 5) |
| `TRADE_API_MAX_GET_RETRIES` | no | Read retries (default 3) |
| `INSTRUMENTS_CACHE_PATH` | no | Disk cache for the instruments file (default `data/instruments.csv.gz`) |
| `GEMINI_API_KEY` | yes for chat | Google AI Studio key, usually starting with `AIza` |
| `GEMINI_MODEL` | no | Default `gemini-2.5-flash` |
| `CHAT_MAX_MESSAGE_CHARS`, `CHAT_RATE_LIMIT_PER_MINUTE`, `CHAT_MAX_TOOL_CALLS` | no | Chat guards (1000 / 20 / 6) |
| `BACKFILL_DAYS` | no | Days of daily history to keep and backfill (default 400) |
| `TRADING_KILL_SWITCH` | no | `true` blocks all new cards and all approvals immediately after restart (default `false`) |
| `MAX_ORDER_VALUE_PAISE`, `MAX_ORDER_QTY` | no | Per-order safety limits, checked when the card is built **and** at approval (defaults ₹2,00,000 and 5,000) |
| `ALLOWED_EXCHANGES`, `ALLOWED_PRODUCTS` | no | Exchanges/products Kraken may trade (defaults `NSE,NSEFO` and `CNC,INTRADAY,NRML`) |
| `WATCHLIST_SYMBOLS`, `PRICE_POLL_INTERVAL_SECONDS`, `OPTIONS_POLL_INTERVAL_SECONDS` | no | Inherited analysis polling |

## Start

```bash
docker compose up -d --build
```

The app listens on http://127.0.0.1:8000. Postgres and Redis run inside the container and are not reachable from the host. Use `docker compose exec app ...` for psql or redis-cli.

On an existing database volume, apply new migrations after pulling. **Order features stay off until migration `kraken_002` has run** (`orders_enabled: false`):

```bash
docker compose exec app python scripts/migrate.py
```

Then restart the app so it picks up the new tables:

```bash
docker compose restart app
```

To view logs:

```bash
docker compose logs -f app
```

## Health checks

- `GET /health`: Redis and DB connectivity (no login needed).
- `GET /v1/copilot/status` (Supabase login needed):

| Field | Healthy value | If not |
|---|---|---|
| `broker_configured` | `true` | Set `TRADE_API_USERNAME` / `TRADE_API_PASSWORD` |
| `broker_token_expires_at` | next 05:00 IST | `null` before the first 021 call; check logs for login errors |
| `instruments_fresh` | `true` | The instruments download is failing; see `last_error` |
| `market_socket_connected` / `market_feed_healthy` | `true` | See "Market socket" below |
| `silent_subscriptions` | `0` | 021 ignored a subscription (unknown token or wrong exchange code) |
| `watchlist_symbols` | number of holdings + open positions | `0` with a non-empty portfolio means watchlist sync is failing |
| `llm_configured` | `true` | Set `GEMINI_API_KEY` |
| `orders_enabled` | `true` | See `orders_error`: usually the migration hasn't run or the DB is down |
| `orders_socket_connected` | `true` | Order status still updates via the REST catch-up on reconnect; check `last_error` |
| `trading_kill_switch` | `false` | `true` means all sending is paused on purpose |

## Emergency stop

Set `TRADING_KILL_SWITCH=true` in `.env` and run `docker compose up -d`. New cards and approvals are refused at once. Orders already at 021 are not touched; cancel them in the 021 app or ask Kraken to "cancel my … order" after turning the switch off.

## Inspecting orders and the audit trail

```bash
docker compose exec app psql "$DATABASE_URL" -c "SELECT state, order_id, order_status, reason, sent_at FROM kraken_order_journal ORDER BY sent_at DESC LIMIT 20;"
docker compose exec app psql "$DATABASE_URL" -c "SELECT at, kind, proposal_id, order_id, data FROM kraken_audit_log ORDER BY id DESC LIMIT 50;"
```

The audit log is append-only: UPDATE and DELETE raise an error by design.

## Read-only check against the real sandbox

```bash
python scripts/smoke_021.py
```

It logs in, counts positions, holdings and orders, downloads and decodes instruments (it prints NIFTY option expiries, so check the dates look right), fetches a socket key and reads the NIFTY price. It never sends orders. **It logs in with the same UCC, which revokes the running app's token**; the app re-logs in on its next call.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Repeated `021 login ok` lines in logs | Another process (a script, a teammate, a second worker) uses the same UCC, and each login revokes the other | One process per UCC; each teammate uses their own account; keep `--workers 1` |
| `021 rejected the UCC or password` | Email used instead of UCC, or wrong password | Use `HACK....` from the 021 Profile page |
| `021 refused access ... account is active` (403) | Account inactive or not a client account | Finish the 021 sign-up (mobile OTP); contact organisers |
| `belongs to another cluster` (421) | Account on another cluster | Contact organisers |
| Market socket reconnecting around 08:00 IST | Daily 021 restart | Expected; it reconnects and resubscribes automatically |
| Socket handshake 403 | Bad or expired ephemeral key | Automatic: a fresh key is fetched on every reconnect |
| `silent_subscriptions > 0` | Unknown token, wrong exchange code, or an invalid `oc` filter | Check the instrument with `get_quote`; refresh instruments |
| Answers say prices are stale | Socket down, or quiet for over 30 s | Check `market_socket_connected` and `last_error`; outside market hours only the last snapshot exists |
| "not enough data for RSI(14)" / symbols skipped in screens | No stored daily history yet (new listing, unmapped symbol, backfill not run, yfinance down) | Wait for the backfill (08:45 IST, or right after a symbol first appears); check Celery logs |
| Chat replies "The language model is unavailable right now." | Gemini key missing or invalid, quota exhausted, or network | Check `GEMINI_API_KEY` and the Google AI Studio quota |
| 401 on `/v1/chat` | Missing or expired Supabase token, wrong `SUPABASE_JWT_SECRET`, or audience mismatch | Log in again; check the secret/JWKS and `SUPABASE_JWT_AUDIENCE` |
| Redis `NOAUTH` / container restarts | `REDIS_PASSWORD` missing, or `REDIS_URL` without the password | Set both (see the table above) |
| Chat says order placement is not enabled | `orders_enabled: false` | Run the migration and restart (see "Start") |
| Approve returns 403 | The UI's origin isn't in `ALLOWED_ORIGINS` | Add the exact origin (scheme://host:port) |
| Approve returns 415 | The request wasn't `Content-Type: application/json` | Send JSON |
| Approve returns 409 `requote` | The price moved more than 0.5% since the card was shown | Use `new_proposal` from the response |
| Journal row `UNKNOWN` | 021 didn't confirm the send | Wait: the reconciler resolves it within ~20 s. It is never resent |
| Journal row `AMBIGUOUS` | Several identical 021 orders could match the send (e.g. one placed manually in the 021 app) | Check the order book in the 021 app; Kraken won't resolve or resend it |
| Journal row `NOT_PLACED` but the order later shows in 021 | 021 booked it very late | The tracker links it when its event arrives and the trader is told (`order_late_link` in the audit log) |
| Orders refused: "instrument list is out of date" | Today's instruments file hasn't been downloaded | Check `instruments_fresh` and `last_error` |

## Rotating credentials

1. Change the secret at its source (021 web app, Google AI Studio, Supabase).
2. Update `.env`.
3. `docker compose up -d` to restart the app container.

## Daily timeline (IST)

| Time | Event |
|---|---|
| 05:00 | 021 access tokens expire; Kraken logs in again on the next call |
| 08:00 | 021 sockets restart; Kraken reconnects and resubscribes |
| Before open | 021 publishes a new instruments file; Kraken re-downloads when its cache is not from today |
| 08:45 Mon–Fri | Celery backfills daily candles for holdings and positions |
| 09:15–15:30 | Market hours; today's forming daily bar is excluded from indicators |
