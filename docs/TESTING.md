# Testing Kraken

The unit suite runs fully offline. It never reads `.env`, never logs in to the real 021 account and never calls Gemini ([tests/conftest.py](../tests/conftest.py) sets `APP_ENV=testing` and blanks the credentials before any import).

```bash
pip install -r requirements-dev.txt
pytest tests/unit -q
ruff check .
```

CI ([.github/workflows/ci.yml](../.github/workflows/ci.yml)) runs ruff, the unit tests and gitleaks on every push and PR. pip-audit runs too, but reports without failing the build.

## Test doubles

### Fake 021: [tests/fakes/fake_021.py](../tests/fakes/fake_021.py)

An in-process fake of the 021 REST API behind `httpx.MockTransport`. Pass `transport=fake.transport()` to `TradeRestClient` (or `KrakenRuntime`).

```python
fake = Fake021()                       # UCC HACK0001 / test-password
fake.positions = [...]; fake.holdings = [...]; fake.trades = [...]
fake.instruments_csv = instruments_csv()

fake.fail_next("/portfolio/positions", status=503, count=2)          # two 503s, then success
fake.fail_next("/trades", status=429, headers={"Retry-After": "2"})  # rate limited
fake.fail_next("/orders", method="POST", exc=httpx.ReadTimeout, accept_first=True)  # books the order, then times out
fake.fail_next("/orders", method="POST", status=500, error="Insufficient funds")     # risk rejection
fake.fail_next("/portfolio/positions", status=502, body=b"<html>")   # non-JSON gateway error
fake.random_fault_rate = 0.3            # 30% of calls get 500/503/429 (seeded RNG)
fake.revoke_token()                     # another login happened elsewhere

fake.count("POST", "/orders")           # how many times a route was hit
fake.logins                             # how many logins happened
```

To keep tests fast, give the client a virtual clock: `sleep` advances the time that the rate limiter reads (see `SleepRecorder` in [test_broker_rest_client.py](../tests/unit/test_broker_rest_client.py)).

### Market data: [tests/fakes/market.py](../tests/fakes/market.py)

- `instruments_csv(expiry_day)`: a small instruments file (RELIANCE on NSE and BSE, INFY, TCS, the HDFC family, M&M, the NIFTY/BANKNIFTY indices, a NIFTY option chain, plus a far expiry).
- Binary frame builders that follow the API guide layouts: `ltp_packet` (with snapshot extras), `full_nsecm`, `full_nsefo`, `full_nseidx`, `full_bse`, `oc_packet`, `heartbeat`, `nse_order_frame`, `bse_order_frame`.
- `seeded_cache(...)` plus `FakeSocket`: prices for tool tests without a websocket.

### LLM

`ScriptedLLM` in [test_chat_service.py](../tests/unit/test_chat_service.py) returns pre-written turns (text or function calls) and records what Kraken sent back.

## What is covered

| Area | Test file |
|---|---|
| 021 client: login sharing, single-flight re-login, read retries, `Retry-After`, no order retries, outcome-unknown, rejections, typed errors | `test_broker_rest_client.py`, `test_rate_limiter.py` |
| Instruments: parsing, lookups, nearest expiry, expiry encodings, freshness, disk cache | `test_instruments.py` |
| Binary packets: every TC and exchange layout, multi-packet frames, snapshot extras, unknown TC | `test_market_packets.py` |
| Socket: reconnect + new key + resubscribe, staleness, cap/eviction, mode upgrades, watchdog | `test_market_socket.py` |
| Runtime: instruments refresh + disk cache, watchlist pinning | `test_runtime.py` |
| L1 tools end to end under faults, with yfinance off (the Phase 1 exit test) | `test_l1_read_tools.py` |
| Chat orchestration: fencing, refused tools/args, budget, order-claim guard, LLM outage, history | `test_chat_service.py` |
| P&L arithmetic in paise | `test_portfolio_math.py` |
| Daily candles: store vs live, stale fallback, forming bar | `test_candle_service.py` |
| Contracts: payload rules, hashes, proposals, plans, instructions | `test_contracts.py` |
| Auth: JWT verification and protected routes | `test_auth.py` |
| Log redaction | `test_redaction.py` |
| Price/expiry text parsing, tick rounding in the trader's favour | `test_parsing.py` |
| Order builder: every L2 validation rule (quantity, half/all, lots, ticks, circuits, SL, product, index, shorts, AMO, limits, kill switch, modify/cancel lookup) | `test_order_builder.py` |
| Approval and execution: single-use, owner, hash, expiry, drift re-quote, source re-check, kill switch, stale instruments, each send outcome, modify/cancel | `test_execution.py` |
| Reconciler and tracker: not placed, ambiguous, linked-order reuse, boot recovery, cancel vs fill, socket fills/rejections, REST catch-up, late links | `test_reconciler_tracker.py` |
| Orders API: card → approve → journal, JSON-only, Origin, owner checks, reject, WebSocket auth and pushes | `test_orders_api.py` |
| Chat + draft tools: cards created, broker never called from chat, clarifications, tools hidden when orders are off | `test_chat_drafts.py` |
| **L2 exit:** 200 runs, random send faults, concurrent double approvals; zero duplicates, exact payloads, truthful journal | `test_l2_exit.py` |

The Level 2 tests share [tests/fakes/orders_world.py](../tests/fakes/orders_world.py), which assembles the fake 021, instruments, prices, builder, in-memory order store, execution service, reconciler and tracker. `Fake021` also supports `order_fault_rate` (random send faults: timeout after booking, timeout before booking, 503, risk rejection), `fill(order_id, qty, price)` and `order_bodies` (exactly what 021 booked).

The Postgres order store has its own tests, which need a database. Run them in the container:

```bash
docker compose exec app python scripts/migrate.py
docker compose exec -e KRAKEN_PG_TESTS=1 app python -m pytest tests/integration/test_order_store_pg.py -q
```

The other `tests/integration` and `tests/e2e` files are inherited and need Postgres/Redis; CI doesn't run them.

## Phase exit criteria

Each phase must pass its exit check under fault injection before the next one starts.

| Phase | Exit check | Status |
|---|---|---|
| 0 | Empty app boots, CI green, contracts merged | done |
| 1 | The four L1 questions + oversold screen answer correctly with 500/503/429 injected and yfinance off | done: `test_l1_read_tools.py` |
| 2 | Zero duplicate orders across 200 runs with random timeouts; sent payload always equals displayed payload | done: `test_l2_exit.py` (a mutation that retries unknown sends makes it fail) |
| 3 | Kill the server mid-fire and restart: the instruction fires exactly once; 1,000 ticks below the level give one order | planned |
| 4 | With one leg forced to reject, the report shows exactly which legs filled or were rejected and why; no silent retries | planned |
| 5 | Chaos runs, prompt-injection red-team set, NL eval set (100+ prompts); every README claim links to code or a test | planned |

## Writing new tests

- Test against `Fake021`, never the real sandbox. Use `scripts/smoke_021.py` (run by hand) for the real thing.
- Inject the failure the sandbox will throw (`fail_next`) and assert the *outcome* the trader sees, not just "no exception".
- Every README claim needs a test name next to it. If you add a claim, add the test in the same PR.
