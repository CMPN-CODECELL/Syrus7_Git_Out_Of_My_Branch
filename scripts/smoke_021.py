"""
Read-only smoke test against the real 021 sandbox, using TRADE_API_* from .env.

    python scripts/smoke_021.py

It logs in, reads positions/holdings/orders, downloads the instruments file, checks the
expiry encoding, fetches a websocket key and reads the NIFTY index price from the market
socket. It never places, modifies or cancels anything, and never prints tokens or passwords.

WARNING: 021 allows one live token per account. Running this while Kraken is running with
the same UCC revokes the app's token (the app re-logs in automatically on its next call).
"""
import asyncio
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config.settings import get_settings  # noqa: E402
from domains.broker.infrastructure.instruments import InstrumentStore, expiry_to_date, parse_instruments_csv  # noqa: E402
from domains.broker.infrastructure.rest_client import TradeRestClient  # noqa: E402
from domains.marketdata.domain.packets import parse_market_frame  # noqa: E402


async def main() -> int:
    s = get_settings()
    if not (s.TradeApiUsername and s.TradeApiPassword):
        print("Set TRADE_API_USERNAME and TRADE_API_PASSWORD in .env first.")
        return 1
    client = TradeRestClient(s.TradeApiBaseUrl, s.TradeApiUsername, s.TradeApiPassword, timeout_seconds=s.TradeApiTimeoutSeconds)
    try:
        positions = await client.get_positions()
        print(f"login ok as {s.TradeApiUsername}; token valid until {client.tokens.expires_at}")
        holdings, orders = await client.get_holdings(), await client.get_orders()
        print(f"positions={len(positions)} holdings={len(holdings)} orders_today={len(orders)}")

        raw = await client.download_instruments()
        rows = parse_instruments_csv(raw.decode("utf-8", errors="replace"))
        store = InstrumentStore(rows, loaded_for=date.today())
        print(f"instruments={len(rows)} by exchange={dict(Counter(r.exchange for r in rows))}")
        nifty = store.index("NIFTY")
        print(f"NIFTY index: {nifty.exchange if nifty else None} token={nifty.token if nifty else None}")
        expiries = store.option_expiries("NIFTY")[:3]
        print("NIFTY option expiries (raw -> decoded):", [(e, str(expiry_to_date(e))) for e in expiries])
        print("nearest expiry used:", expiry_to_date(store.nearest_expiry("NIFTY") or 0))

        key = await client.get_ephemeral_key()
        print("websocket key ok")
        if nifty:
            import websockets

            async with websockets.connect(f"{s.TradeWsBaseUrl}/market?token={key}", open_timeout=10) as ws:
                await ws.send(json.dumps({"Task": "subscribe", "Mode": "ltp", "Instruments": [[nifty.ws_code, nifty.token]]}))
                frame = await asyncio.wait_for(ws.recv(), timeout=10)
                result = parse_market_frame(frame)
                print("market socket packets:", [(p.exchange_code, p.token, p.ltp) for p in result.packets], "error:", result.error)
        return 0
    finally:
        await client.aclose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
