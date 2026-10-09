# AlphaStreams V2 — Local Project Instructions & Context (GEMINI.md)

## System & Environment Profile

- **Runtime Environment**:
  - Local Python: 3.11+
  - Single-container multi-process stack: Docker & Docker Compose (`supervisord` managing FastAPI, Celery Worker, Celery Beat, Redis, and TimescaleDB).
  - Production stack: Multi-service compose in `docker-compose.prod.yml`.
  - Platform note: `uvloop` is Linux-only (enabled inside the container; skipped on Windows host).

---

## 1. Project Overview & Architecture

**AlphaStreams V2** is an event-driven quantitative options analytics platform and trading dashboard tailored for the Indian financial markets (NSE/BSE).

The codebase is built as a **Modular Monolith** adhering to **Domain-Driven Design (DDD)** and **Hexagonal (Ports & Adapters) Architecture**.

```text
domains/
├── ingestion/       # External market data providers (Groww, NSE, yfinance), session management, raw tick streams
├── analytics/       # Black-Scholes-Merton (BSM), Crank-Nicolson PDE, Greeks (Δ, Γ, ν, θ, ρ), Technical Indicators
├── notifications/   # Real-time alert rules engine, condition matching (Price/IV/Delta), cooldown & dispatching
└── historical/      # TimescaleDB OHLC hypertable persistence & historical bar queries
app/                 # FastAPI configuration, lifespan hooks, route bootstrapping, static file serving
shared/              # Cross-cutting kernel (Redis connection pools, Event Bus contracts, constants, middleware, utils)
frontend/            # Glassmorphic dark-theme NSE dashboard (Vanilla HTML5, CSS3, Vanilla JS, Supabase Auth)
```

---

## 2. Core Architectural & Engineering Rules

### Bounded Context & Layer Isolation

1. **Zero Direct Inter-Domain Imports**: Never import code directly between bounded contexts (e.g., `domains.ingestion` MUST NOT import `domains.analytics` or vice versa).
2. **Event-Driven Communication**: All inter-domain coordination must flow through **Redis Streams** (durable events) or **Redis Pub/Sub** using contracts defined in [contracts.py](file:///d:/Nirmay%20pc/ENGINEERING/projects/MarketSentimentAnalysis2/shared/infrastructure/event_bus/contracts.py) and [constants.py](file:///d:/Nirmay%20pc/ENGINEERING/projects/MarketSentimentAnalysis2/shared/constants.py).
3. **Hexagonal Layers inside each domain**:
   - `domain/`: Pure business entities, value objects, mathematical formulas (no external dependencies).
   - `ports/`: Inbound and outbound abstract interface contracts (e.g., `IMarketPriceSourcePort`, `IOptionChainSourcePort`).
   - `application/`: Orchestrators, use-case services, Celery task handlers.
   - `infrastructure/`: Database repositories, outbound API clients, Redis adapters.
   - `api/`: Inbound driving HTTP/WebSocket routers and Pydantic DTOs.

### Zero Mock / Synthetic Data Policy

- **Never insert fake prices, synthetic spreads, or dummy responses** in domain, application, or infrastructure code.
- Bid/ask spreads and IV must be authentic market data or explicit `None` / `0.0`.
- When live market data feeds fail or upstream APIs are unreachable, fail fast with explicit exceptions / `HTTP 503 Service Unavailable`, or render clear "Data Unavailable" UI states.

### Persona & Coding Standards

- **Persona**: Expert Principal-Level Software Engineer & Quantitative Systems Architect.
- **Python**: Follow PEP 8 strictly. Use explicit type hints for all function arguments and return types.
- **Async First**: All FastAPI endpoints, Redis operations, and network I/O must be asynchronous (`async`/`await`).
- **Structured Logging**: Use `logging.getLogger(__name__)` everywhere. Never use `print()`.
- **Clean Code**: Prioritize early returns and guard clauses. Avoid deeply nested `if/else` logic.
- **No Placeholders**: Never output placeholders like `# ... rest of code` or `# TODO: implement`. Output complete, production-ready code.

### Security, Auth & Configuration

- Never hardcode secrets, API keys, tokens, or connection strings.
- Manage configuration exclusively via Pydantic `Settings` in [settings.py](file:///d:/Nirmay%20pc/ENGINEERING/projects/MarketSentimentAnalysis2/app/config/settings.py) and `.env` (use `.env.example` as template).
- **Authentication**:
  - `APIKeyAuthMiddleware` protects `/v1/ingestion/*` (requires `X-API-Key: {settings.InternalApiKey}`).
  - Mutation endpoints (`POST/DELETE /v1/notifications/alerts`) require `Authorization: Bearer <token>`.
- **CORS & Config Protection**: `GET /config` rejects unauthorized cross-origin requests in production. Default CORS whitelist is restricted to explicit localhost origins.
- **WebSocket Limits**: Enforce `_MAX_CLIENTS_PER_SYMBOL = 100` and 60-second ping/pong timeout.

---

## 3. Key Technical Conventions & Patterns

### Event Loop, Connection Pools & Performance

- **Celery Tasks**: Use `_get_or_create_loop()` in task modules (e.g., `ingestion_tasks.py`). Never call `asyncio.run()` inside frequently running tasks.
- **Persistent Sessions**: Reuse Redis pools, PostgreSQL/asyncpg pools (`min_size=2`, `max_size=10`), and `aiohttp`/`httpx` client sessions.
- **Symbol Caching**: Use `@lru_cache(maxsize=2000)` on `SymbolValidator.get_clean_symbol` to avoid repeated string parsing.

### WebSocket Routing & Mounts

- `events_router` MUST be included in `app/main.py` at both root (`/ws/{symbol}`) and `/v1` (`/v1/ws/{symbol}`) before `app.mount("/", StaticFiles...)` to ensure WebSocket handshakes never fall through to `StaticFiles`.

### Redis Keys, Channels & Streams

Always reference [constants.py](file:///d:/Nirmay%20pc/ENGINEERING/projects/MarketSentimentAnalysis2/shared/constants.py):

- **Pub/Sub Channels**: `Channels.PRICE_UPDATED`, `Channels.OPTIONS_UPDATED`, `Channels.ALERT_DISPATCHED`
- **Redis Streams**: `Streams.PRICE_TRIGGER`, `Streams.OPTIONS_RAW_FETCHED`, `Streams.OPTIONS_PRICED`, `Streams.ANALYSIS_REFRESH_REQUESTED`
- **Keys & TTL**: `RedisKeys.MARKET_PRICE`, `RedisKeys.MARKET_OPTIONS`, `RedisKeys.MARKET_OPTIONS_PRICED` using `TTL.MARKET_PRICE` (60s), `TTL.MARKET_OPTIONS` (120s)

### Market Data Adapter Architecture

- Market data ingestion uses a pluggable factory `get_market_data_adapter()` in `domains/ingestion/infrastructure/outbound/adapter_factory.py`.
- Selection is driven by `MARKET_DATA_PROVIDER` (`groww` or `nse`).
- Adapters must implement both `IMarketPriceSourcePort` and `IOptionChainSourcePort`.

---

## 4. Development & Testing Commands

### Dependencies

- **Runtime**: `requirements.txt` (lean production dependencies).
- **Development/Testing**: `requirements-dev.txt` (includes pytest, pytest-asyncio, scikit-learn, matplotlib).

### Testing with Pytest

```bash
# Run unit tests locally
pytest tests/unit/ -v

# Run integration tests locally
pytest tests/integration/ -v

# Run full test suite inside Docker container
docker compose exec app python -m pytest tests/ -v
```

### Docker & Container Operations

```bash
# Start local single-container dev stack
docker compose up -d

# View live container logs
docker compose logs -f app

# Rebuild dev container after dependency changes
docker compose up -d --build

# Start production multi-service stack
docker compose -f docker-compose.prod.yml up -d
```

### Database Migrations

```bash
# Apply migrations with version tracking
python scripts/migrate.py

# Inside Docker container
docker compose exec app python scripts/migrate.py
```

### Git & Commits

- Follow **Conventional Commits**: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `perf:` (subject ≤ 72 chars).
- **Rule**: Never run `git add`, `git commit`, or `git push` automatically without explicit user confirmation.
