# Kraken API for the chat UI

The reference client is the dashboard's Copilot tab ([frontend/copilot.js](../frontend/copilot.js)), which follows every rule below.

All endpoints need a Supabase access token: `Authorization: Bearer <supabase access_token>`. A missing, expired or forged token returns `401`. Keep the token in JavaScript storage and send it as a header; **never put it in a cookie**. Kraken uses no CSRF token, and that is only safe while auth stays header-based (ADR-011).

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
  "proposals": [],
  "request_id": "9f1c..."
}
```

Rendering rules:
- Render `reply` as plain text or markdown, using `textContent` or a sanitizer. Never use raw `innerHTML`: the reply can quote broker-supplied text.
- Tables and numbers should come from `data[].result`, not from parsing `reply`. Each `result` has `as_of`, a definition/basis field, stale flags, and `warnings` or `skipped` lists worth showing.
- If `llm_available` is `false`, the assistant is down. Show `reply` as a system notice.
- **Order cards:** for every id in `proposals`, fetch `GET /v1/proposals/{id}` and render the card **from that response only**. Never build a card from `reply` text (see "Orders" below).

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
| `draft_order`, `draft_modify_order`, `draft_cancel_order` | `status`: `proposed` (with `proposal_id`, `card`, `expires_in_seconds`) / `needs_clarification` (`message`, `options[]`) / `refused` (`message`) |

## Orders

The flow:
1. The chat creates a card (`proposals` in the chat response).
2. The UI shows it from `GET /v1/proposals/{id}`.
3. The trader clicks **Approve** or **Reject**.
4. Live status arrives on `WS /v1/stream/orders`, with `GET /v1/orders` as the polling fallback.

Typing "yes" in chat approves nothing; only the Approve call does.

### GET /v1/proposals/{id}

Returns `404` for unknown ids and for other users' proposals.

```json
{
  "proposal_id": "6f1d...", "kind": "PLACE", "state": "PROPOSED", "state_reason": null,
  "card": {
    "action": "PLACE", "symbol": "RELIANCE", "exchange": "NSE", "side": "BUY", "quantity": 10, "lots": null, "lot_size": null,
    "order_type": "MARKET", "product": "CNC", "validity": "Day", "limit_price_paise": null, "trigger_price_paise": null,
    "amo": false, "target_order_id": null, "reference_ltp_paise": 280000, "reference_ltp_as_of": "2026-10-09T05:40:12Z",
    "estimated_value_paise": 2800000, "notices": []
  },
  "payload": {"exchange": "NSE", "token": 2885, "qty": 10, "price": 0, "book": "RL", "product": "CNC", "validity": "Day"},
  "payload_hash": "3b5e...64 hex...",
  "target_order_id": null, "created_at": "...", "expires_at": "...", "seconds_left": 57
}
```

Card rendering rules:
- Show every card field the trader needs to judge the order: side, quantity (and lots × lot size for F&O), symbol, exchange, order type, limit and trigger prices (₹ = paise / 100), product, validity, **AMO badge** when `amo` is true, reference price with its time, estimated value, and **every** string in `notices` (rounding, expiry used, "half of 7 = 3", AMO).
- For `MODIFY` and `CANCEL`, show `target_order_id` and say clearly "Modify order #…" / "Cancel order #…".
- Show a countdown from `seconds_left`. At 0, disable Approve (the server refuses expired cards anyway).
- Render text with `textContent`.

### POST /v1/proposals/{id}/approve

This is the only call that sends an order to 021.

- Headers: `Authorization: Bearer <jwt>`, `Content-Type: application/json`.
- Body: `{"payload_hash": "<payload_hash from GET /v1/proposals/{id}>"}`. Send back exactly the hash of the card you displayed.
- Rejected before any processing: wrong content type → `415`; an `Origin` not in `ALLOWED_ORIGINS` → `403`; a malformed body → `422`; more than 30 approvals per minute → `429`.

| HTTP | `status` | Meaning | UI action |
|---|---|---|---|
| 200 | `sent` | 021 accepted it; `order.order_id` is set | Show "Sent", then follow live updates |
| 200 | `rejected` | 021's risk checks rejected it; `order.reason` says why | Show the reason |
| 200 | `not_sent` | 021 never processed it (connection, or the session was replaced by another login); `message` says why. `new_proposal` usually holds a fresh card | Show `new_proposal` as a new card (or ask for one) |
| 200 | `unknown` | Sent, but 021 didn't confirm; Kraken is checking the order book and will **not** resend | Show "Checking…" until the live update resolves it |
| 409 | `requote` | The price moved more than 0.5%; nothing sent; `new_proposal` holds a fresh card | Replace the card with `new_proposal` |
| 409 | `refused` | Already approved/rejected, hash mismatch, or a pre-send check failed (holding changed, stale instruments, no fresh price, order no longer open) | Show `message` |
| 410 | `refused` | Card expired | Ask for a fresh card |
| 423 | `refused` | Kill switch is on | Show `message` |
| 404 | `refused` | Not found / not yours | — |

Response body: `{status, message, order, proposal, new_proposal, request_id}`. `order` uses the journal shape below.

### POST /v1/proposals/{id}/reject

Same headers as approve; the body may be `{}`. Returns the proposal in state `REJECTED`.

### GET /v1/orders and GET /v1/orders/{journal_id}

The user's order journal, newest first (`?limit=` up to 200):

```json
{ "orders": [ {
  "journal_id": "…", "proposal_id": "…", "action": "PLACE",
  "state": "ACKED", "order_id": "1042", "order_status": "Executed",
  "filled_qty": 10, "avg_fill_price_paise": 280050, "reason": null,
  "sent_at": "…", "updated_at": "…", "payload": { … }, "card": { … }
} ] }
```

- `state` (Kraken's view of the send): `SENDING`, `ACKED`, `REJECTED`, `NOT_SENT`, `UNKNOWN`, `NOT_PLACED` (021 has no such order), `AMBIGUOUS` (several 021 orders could match; the trader must check, nothing is resent).
- `order_status` (021's view): `Received`, `Placed`, `Pending`, `Executed`, `Rejected`, `Cancelled`, `SentForModification`, `SentForCancellation`, `AcceptedForAMO`, …

### WS /v1/stream/orders

1. Connect from an allowed origin. The browser can't put headers on a WebSocket, so send the token in the first message:
   ```json
   {"type": "auth", "token": "<supabase access_token>"}
   ```
   You have 5 seconds. A bad token closes the socket with code `4401`; a foreign origin closes it with `4403`.
2. Server replies `{"type": "ready"}`.
3. Server pushes `{"type": "order_update", "order": {…journal shape…}}` whenever a send result, reconciliation, fill, rejection or cancel changes one of your orders.
4. Optional keep-alive: send `{"type": "ping"}` and receive `{"type": "pong"}`.

If the socket drops, reconnect and call `GET /v1/orders` once to catch up.

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
  "last_watchlist_sync": "2026-10-09T05:31:00+00:00", "llm_configured": true, "last_error": null,
  "orders_enabled": true, "orders_error": null, "orders_socket_connected": true, "trading_kill_switch": false
}
```

When `orders_enabled` is `false`, hide Approve buttons and show `orders_error`.

## Removed endpoints

These routes were removed with the Black-Scholes/PDE code:
- `POST /v1/pricer/calculate` (BSM calculator)
- `GET /v1/export/research`

`GET /v1/pricer/ticker/{symbol}` still serves the option-chain side panel, without model-implied IV. In `GET /v1/derivatives/{symbol}`, `fair_priced_chain` is now always empty.
