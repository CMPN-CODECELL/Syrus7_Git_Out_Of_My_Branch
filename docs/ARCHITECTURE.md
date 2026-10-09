# Kraken architecture

This page describes the system as it is built today (Level 1, read-only). Parts planned for Levels 2–4 are marked **planned** and do not exist in the code yet. See [ROADMAP.md](ROADMAP.md).

## 1. The invariant

> The LLM can only read. It never has a tool that sends, modifies or cancels an order.

In Level 1 this holds because no order tool exists ([tool_specs.py](../domains/copilot/domain/tool_specs.py)). From Level 2 on, the LLM may also *draft*. Deterministic code turns a draft into a server-side proposal, and only an authenticated human click on that exact proposal can send it (see [DECISIONS.md](DECISIONS.md), ADR-001).

## 2. System context

```mermaid
flowchart LR
  Trader((Trader)) -->|browser| UI["Web chat UI<br/>(frontend/, owned by UI team)"]
  UI -->|"Supabase login"| SB[(Supabase Auth)]
  UI -->|"HTTPS + Bearer JWT"| API["Kraken API<br/>FastAPI, 1 uvicorn worker"]
  API -->|"function calling"| GEM["Gemini<br/>(google-genai)"]
  API -->|"REST, binary websocket"| T021["021 Trade sandbox"]
  API --> REDIS[(Redis)]
  API --> PG[(Postgres + TimescaleDB)]
  CEL["Celery worker + beat"] --> REDIS
  CEL --> PG
  CEL -->|"daily history"| YF["yfinance / NSE"]
  API -->|"side-panel analysis"| YF
```

Everything except Supabase, Gemini, 021 and yfinance/NSE runs in one container ([Dockerfile](../Dockerfile), [docker/supervisord.conf](../docker/supervisord.conf)): uvicorn, Celery worker, Celery beat, Redis, Postgres/Timescale and the ingestion orchestrator. Only port 8000 is published.

## 3. Components

```mermaid
flowchart TB
  subgraph app["app/"]
    MAIN["main.py<br/>middleware, routers, lifespan"]
    RT["runtime.py<br/>KrakenRuntime"]
  end
  subgraph copilot["domains/copilot"]
    ROUTER["api/router.py<br/>/v1/chat, /v1/copilot/status"]
    CHAT["application/chat_service.py<br/>CopilotChatService"]
    TOOLS["application/read_tools.py<br/>ReadToolbox"]
    SPECS["domain/tool_specs.py<br/>tool schemas + arg models"]
    MATH["domain/portfolio_math.py<br/>pure paise arithmetic"]
    GEMA["infrastructure/gemini_adapter.py"]
    PORT["ports.py<br/>LLMPort"]
  end
  subgraph broker["domains/broker (only code that talks to 021)"]
    REST["rest_client.py<br/>TradeRestClient"]
    TOK["token_manager.py"]
    RL["rate_limiter.py<br/>TokenBucket"]
    ERR["domain/errors.py"]
    INS["instruments.py<br/>InstrumentStore + disk cache"]
  end
  subgraph md["domains/marketdata"]
    SOCK["market_socket.py<br/>MarketSocketClient"]
    PKT["domain/packets.py<br/>binary parsers"]
    PC["domain/price_cache.py"]
    SMAP["domain/symbol_map.py"]
  end
  subgraph hist["domains/historical"]
    CS["application/candle_service.py"]
    YFD["infrastructure/yfinance_daily.py"]
    REPO["persistence/ohlc_repository.py"]
    TASK["tasks.py (Celery backfill)"]
  end
  TECH["domains/analytics/.../technical_indicators_engine.py"]
  CONTRACTS["shared/contracts<br/>OrderPayload, OrderProposal, Plan, ..."]
  AUTH["shared/auth<br/>Supabase JWT verification"]

  MAIN --> ROUTER --> CHAT --> PORT --> GEMA
  ROUTER --> AUTH
  CHAT --> SPECS
  CHAT --> TOOLS --> MATH
  TOOLS --> REST
  TOOLS --> INS
  TOOLS --> SOCK
  TOOLS --> PC
  TOOLS --> CS --> REPO
  CS --> YFD
  TOOLS --> TECH
  TOOLS --> SMAP
  REST --> TOK
  REST --> RL
  REST --> ERR
  SOCK --> PKT
  SOCK --> PC
  RT --> REST
  RT --> INS
  RT --> SOCK
  RT --> CHAT
  TASK --> YFD
  TASK --> REPO
  REST -.-> CONTRACTS
```

| Module | Responsibility | Owner (team split) |
|---|---|---|
| `domains/broker` | 021 login, REST calls, error types, rate limit, read retries, instruments master | A |
| `domains/marketdata` | Market socket, binary parsing, price cache, 021 ↔ yfinance symbol map | B |
| `domains/historical` | Daily candles: Timescale store, yfinance fetch, Celery backfill | B |
| `domains/copilot` | LLM port and Gemini adapter, read tools, chat orchestration, chat API | C (tools/LLM), D (API) |
| `shared/contracts` | Cross-team Pydantic models (paise ints, `extra="forbid"`) | all; changes need review from both sides of a seam |
| `shared/auth`, `shared/middleware/auth.py` | Supabase JWT verification | D |
| `domains/analytics`, `domains/ingestion`, `domains/notifications` | Inherited analysis feed, side-panel endpoints and legacy alerts | B / D |

## 4. Process model

- **One uvicorn worker.** 021 allows one live token per account, and a new login revokes the previous token. The worker owns the only `TradeRestClient`, its `TokenManager` and the market socket ([ADR-002](DECISIONS.md#adr-002-one-uvicorn-worker-owns-the-021-session)).
- **`KrakenRuntime`** ([app/runtime.py](../app/runtime.py)) is created in the FastAPI lifespan and stored on `app.state.kraken`. It starts three background activities:

| Loop | Interval | What it does |
|---|---|---|
| Instruments | checks every 30 min | Loads today's disk cache at startup; downloads the 021 instruments CSV when the cache is not from today's IST date |
| Market socket | continuous | Connect → resubscribe → read; reconnects with backoff (1 s doubling to 30 s, ×0.5–1.5 jitter) |
| Watchlist | every 60 s | Reads holdings and positions, pins their prices on the socket (`ltpc` mode), publishes the analysis watchlist to Redis, and queues a backfill for new symbols |

- **Celery** runs analysis jobs only (option-chain snapshots, daily candle backfill at 08:45 IST on weekdays). It never logs in to 021. It reads the watchlist from the Redis hash `kraken:analysis:watchlist` that the app writes ([domains/historical/tasks.py](../domains/historical/tasks.py)).
- If the 021 credentials are missing, the runtime starts with broker features disabled, and tools answer "021 credentials are not configured".

## 5. Request flow: a chat question

```mermaid
sequenceDiagram
  autonumber
  participant UI
  participant API as /v1/chat
  participant Auth as require_user
  participant Chat as CopilotChatService
  participant LLM as Gemini
  participant Tools as ReadToolbox
  participant B as TradeRestClient
  participant S as MarketSocket/PriceCache

  UI->>API: POST {message} + Bearer JWT
  API->>Auth: verify signature, exp, aud, sub
  API->>API: per-user rate limit, length cap
  API->>Chat: handle(user_id, message)
  Chat->>LLM: system prompt + history (text only) + read-only tool declarations
  LLM-->>Chat: function_call get_pnl {}
  Chat->>Chat: validate args (strict model, extra keys rejected)
  Chat->>Tools: get_pnl()
  Tools->>B: GET positions, holdings, trades (retries on 429/5xx)
  Tools->>S: ensure prices subscribed, wait up to 2.5 s for fresh quotes
  Tools-->>Chat: result (paise + display strings, as_of, definition, warnings)
  Chat->>LLM: function_response {"untrusted_data": result, "note": ...}
  LLM-->>Chat: final text
  Chat->>Chat: order-claim guard
  Chat-->>API: reply + tool traces + structured data
  API-->>UI: JSON (UI renders numbers from data)
```

Limits: at most `CHAT_MAX_TOOL_CALLS` (6) tool calls per message, 25 s per tool call, and the last 12 text messages (user + assistant) are remembered per user. Tool results are never stored in the history.

## 6. Two price sources, one rule

| Source | Used for | Never used for |
|---|---|---|
| **021** (REST + market socket) | Positions, holdings, trades, P&L, LTP, option chain (`oc` mode), and (planned) every order price, trigger and drift check | — |
| **yfinance / NSE** | Daily history for indicators; the inherited option-chain side panel | Order prices, P&L, triggers |

`get_technicals` compares the latest analysis price with the 021 LTP and flags any gap above 1%. Symbol mapping lives in [symbol_map.py](../domains/marketdata/domain/symbol_map.py): `<SYMBOL>.NS` for NSE cash, `.BO` for BSE, plus an explicit index table. Unmappable instruments are reported as skipped.

## 7. The 021 gateway

### Token lifecycle

```mermaid
stateDiagram-v2
  [*] --> NoToken
  NoToken --> Valid: login (POST /auth/token)
  Valid --> Valid: request ok
  Valid --> Refreshing: 401, or within 2 min of expiresAt (5:00 IST)
  Refreshing --> Valid: single-flight login<br/>(concurrent callers wait and reuse it)
  Refreshing --> NoToken: login failed (error raised)
```

### Retry policy

| Request | 429 / 500 / 503 / timeout / non-JSON | 401 | Connection never opened |
|---|---|---|---|
| **Read (GET)** | Retry up to 3× with full-jitter backoff (0.5·2ⁿ s, cap 8 s); 429 honours `Retry-After` and pauses the shared limiter | Re-login once, replay once | Retry |
| **Order action** (POST/PUT/DELETE `/orders`) | **No retry.** 500 with error text → `BrokerRejectedError`; other 5xx or lost response → `BrokerOutcomeUnknownError` | Re-login, report **not sent**, no replay | `BrokerUnavailableError` ("not sent") |

The order methods exist in [rest_client.py](../domains/broker/infrastructure/rest_client.py) and are tested. In Level 1 nothing calls them.

### Instruments

The ~1,05,000-row CSV is parsed into `Instrument` models. Only known columns are kept, so a new column cannot break parsing, and malformed rows are counted and skipped. It is indexed by `(exchange, token)`, symbol and ISIN, and cached as gzip with a date sidecar. Freshness is judged by IST trading date. The `expiry` encoding is auto-detected (see [instruments.py](../domains/broker/infrastructure/instruments.py), `expiry_to_date`).

## 8. Market data

### Socket lifecycle

```mermaid
stateDiagram-v2
  [*] --> FetchingKey
  FetchingKey --> Connecting: GET /websocket/ephemeral-key
  Connecting --> Subscribing: handshake ok
  Subscribing --> Streaming: send subscribe JSON per mode (all wanted instruments)
  Streaming --> Streaming: binary frames → parse → PriceCache
  Streaming --> Backoff: close / error / 08:00 IST restart
  FetchingKey --> Backoff: error
  Connecting --> Backoff: 403 / error
  Backoff --> FetchingKey: sleep 1→30 s with jitter
```

- **Subscriptions** are remembered client-side and re-sent on every connection. Modes only ever upgrade (`ltp` < `ltpo`/`ltpc` < `full` < `oc`).
- **Cap:** 100 instruments per connection. Pinned instruments (holdings/positions) are never evicted. Ad-hoc ones (a quote, an option chain) are evicted least-recently-requested first.
- **Watchdog:** a subscription with no data after 10 s is re-sent, up to 2 times, then reported as silent in `/v1/copilot/status`.
- **Staleness** ([price_cache.py](../domains/marketdata/domain/price_cache.py)) is decided per connection, not per tick. A quote is stale if the socket is down, no frame (including heartbeats) arrived for 30 s, or the quote came from a previous connection.

### Packet parsing

[packets.py](../domains/marketdata/domain/packets.py) walks each frame by transaction code: TC 1 LTP (12 bytes, plus 5 snapshot bytes for `ltpo`/`ltpc`), TC 3 full (220/234/36/262 bytes by exchange code), TC 9 option chain (variable), TC 10 heartbeat. An unknown TC stops parsing and reports the remaining byte count. Orders-socket packets (TC 4 NSE, TC 8 BSE) are parsed too, for Level 2.

## 9. Daily candles and indicators

```mermaid
flowchart LR
  RT["KrakenRuntime watchlist loop"] -->|"HSET kraken:analysis:watchlist"| R[(Redis)]
  RT -->|"send_task backfill (new symbols)"| CEL[Celery]
  BEAT["beat 08:45 IST Mon-Fri"] --> CEL
  CEL -->|"read watchlist"| R
  CEL -->|"~400 days, adjusted"| YF[yfinance]
  CEL -->|"upsert 1d candles"| TS[(OhlcCandles hypertable)]
  TOOL["get_technicals / screen_portfolio"] --> CS[CandleService]
  CS -->|"1. stored candles"| TS
  CS -->|"2. live fetch only if stored data is behind"| YF
```

`CandleService` returns `CandleSeries` with `source`, `as_of`, `bar_count`, `stale` and `excluded_partial_bar`. Today's still-forming daily bar is dropped during market hours. Indicator math is in [technical_indicators_engine.py](../domains/analytics/domain/services/technical_indicators_engine.py): RSI(14) with Wilder smoothing returns `None` when there are fewer than 15 closes. A portfolio screen allows at most 8 live yfinance fetches per question. The rest are served from storage or listed as skipped.

## 10. Contracts and units

All cross-module models are in [shared/contracts](../shared/contracts):

- `Instrument`: one instruments-file row; `request_exchange` maps `NSECM→NSE` and so on, and is `None` for indices (data only).
- `OrderPayload`: the exact 021 order body. It validates the qty sign, SL needs a trigger, CNC is cash-only and NRML is F&O-only. `payload_hash()` is the SHA-256 of the canonical JSON.
- `OrderDraft`: what the LLM may extract (planned use in Level 2). There is no default quantity.
- `OrderProposal`, `Plan`, `StandingInstruction`: hash-checked on construction (planned use in Levels 2–4).
- `OrderEvent`, `PriceQuote`.

Units: prices are `int` paise everywhere; ₹ formatting happens only for display (`portfolio_math.rupees`). Quantity sign is the side.

## 11. Order lifecycle (planned, Level 2)

```mermaid
stateDiagram-v2
  [*] --> DRAFTED: LLM draft_order
  DRAFTED --> PROPOSED: validator ok, proposal row + payload hash, TTL 60 s
  DRAFTED --> [*]: validation failed (explained)
  PROPOSED --> APPROVED: human click, CAS PROPOSED→APPROVED, hash match, not expired, drift ≤ 0.5%
  PROPOSED --> EXPIRED: TTL / price drift
  APPROVED --> SENDING
  SENDING --> ACKED: 200 + orderId
  SENDING --> REJECTED: BrokerRejectedError
  SENDING --> UNKNOWN: BrokerOutcomeUnknownError
  UNKNOWN --> ACKED: reconciler finds it in GET /orders
  UNKNOWN --> NOT_PLACED: reconciler confirms absent
  ACKED --> OPEN
  OPEN --> EXECUTED
  OPEN --> PARTIAL
  OPEN --> CANCELLED
  OPEN --> REJECTED
  PARTIAL --> EXECUTED
```

None of this exists yet beyond the contracts, the no-retry order methods and the orders-socket parser.

## 12. Configuration

All settings are in [app/config/settings.py](../app/config/settings.py), read from `.env` (template: [.env.example](../.env.example)). The variables are described in [RUNBOOK.md](RUNBOOK.md#environment-variables). Tests use `TestingSettings`, which never reads `.env`.

## 13. Directory map

```
app/                    FastAPI app, settings, Celery config, KrakenRuntime
domains/broker/         021 REST client, token manager, rate limiter, errors, instruments
domains/marketdata/     market socket, packet parsers, price cache, symbol map
domains/copilot/        LLM port + Gemini adapter, read tools, chat service, chat API
domains/historical/     daily candles, yfinance fetch, Celery backfill
domains/analytics/      technical indicators engine (+ inherited side-panel endpoints)
domains/ingestion/      inherited NSE/yfinance analysis feed
domains/notifications/  inherited alert rules (dormant until Level 3)
shared/contracts/       cross-team models
shared/auth/            Supabase JWT verification
shared/logging/         structured logging + secret redaction
tests/fakes/            fake 021 (fault injection) and market-data builders
tests/unit/             offline test suite
scripts/                migrations, read-only 021 smoke test
docs/                   this documentation
```
