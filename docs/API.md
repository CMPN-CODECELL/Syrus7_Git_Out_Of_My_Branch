# Kraken API for the chat UI

All endpoints need a Supabase access token: `Authorization: Bearer <supabase access_token>`. A missing, expired or forged token returns `401`.

## POST /v1/chat

Request:

```json
{ "message": "Which positions are down more than 5%?" }
```

- `message` is required, at most `CHAT_MAX_MESSAGE_CHARS` (default 1000) characters.
- `429` after `CHAT_RATE_LIMIT_PER_MINUTE` messages per minute per user.

Response `200`:

```json
{
  "reply": "Two holdings are down more than 5% vs your average price: ...",
  "llm_available": true,
  "tools": [
    { "name": "filter_positions", "args": {"threshold_pct": 5, "direction": "down", "scope": "both"}, "ok": true, "error": null, "duration_ms": 412 }
  ],
  "data": [
    { "tool": "filter_positions", "args": {"threshold_pct": 5, "direction": "down", "scope": "both"},
      "result": { "as_of": "2026-10-09T11:02:13+05:30", "basis": "...", "matches": [ { "symbol": "M&M", "move_pct": -6.67, "ltp": "Rs 2,800.00" } ] } }
  ],
  "request_id": "9f1c..."
}
```

Rendering rules:
- Render `reply` as plain text or markdown, using `textContent` or a sanitizer. Never use raw `innerHTML`: the reply can quote broker-supplied text.
- Tables and numbers should come from `data[].result`, not from parsing `reply`. Each `result` has `as_of`, a definition/basis field, stale flags, and `warnings` or `skipped` lists worth showing.
- If `llm_available` is `false`, the assistant is down. Show `reply` as a system notice.
- In this version Kraken never returns an approvable order. There is no approve endpoint yet; see the README "Future scope".

`result` shapes per tool (keys are stable; amounts are display strings like `"Rs 1,23,456.78"`, plus `*_paise` integers where useful):

| tool | key fields |
|---|---|
| `get_pnl` | `positions[]`, `positions_total`, `holdings[]`, `holdings_total`, `definition`, `warnings[]` |
| `filter_positions` | `matches[]` (`kind`, `symbol`, `qty`, `avg_price`, `ltp`, `move_pct`), `result`, `basis`, `not_checked_no_price[]` |
| `get_average_price` | `held`, `holding_average[]`, `today_positions[]`, `note` |
| `get_quote` | `symbol`, `ltp`, `prev_close`, `quote_time`, `stale` |
| `option_chain_near_atm` | `underlying`, `expiry`, `spot`, `atm_strike`, `lot_size`, `rows[]` (`strike`, `atm`, `ce`/`pe`: `ltp`, `oi`, `iv_pct`, `delta`, `stale`) |
| `get_technicals` | `rsi14`, `rsi14_zone`, `sma50`, `sma200`, `close_vs_sma200`, `macd`, `macd_state`, `bars`, `data_as_of`, `price_source_check`, `definitions`, `disclaimer` |
| `screen_portfolio` | `definition`, `matches[]`, `not_matching[]`, `skipped[]` (`symbol`, `reason`) |

## DELETE /v1/chat/history

Clears this user's conversation context. Returns `204`.

## GET /v1/copilot/status

Health of the moving parts, for a status indicator:

```json
{
  "broker_configured": true, "broker_token_expires_at": "2026-10-10T05:00:00+05:30",
  "instruments_loaded": 105123, "instruments_for": "2026-10-09", "instruments_fresh": true,
  "market_socket_connected": true, "market_feed_healthy": true, "market_socket_connects": 2,
  "subscriptions": 14, "silent_subscriptions": 0, "watchlist_symbols": 9,
  "last_watchlist_sync": "2026-10-09T05:31:00+00:00", "llm_configured": true, "last_error": null
}
```

## Removed endpoints

These routes were removed with the Black-Scholes/PDE code:
- `POST /v1/pricer/calculate` (BSM calculator)
- `GET /v1/export/research`

`GET /v1/pricer/ticker/{symbol}` still serves the option-chain side panel, without model-implied IV. In `GET /v1/derivatives/{symbol}`, `fair_priced_chain` is now always empty.
