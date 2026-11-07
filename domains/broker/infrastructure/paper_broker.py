"""
Paper broker implementation for Kraken AI Trading Copilot.

Provides a fully in-memory simulated broker and market data feed that mirrors 021 Trade's
REST API and WebSocket protocol. Enables complete end-to-end testing, local development,
and simulated trading without any live broker credentials or active network connectivity.
"""
import asyncio
import gzip
import itertools
import json
import logging
import math
import os
import random
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

import httpx

from domains.broker.infrastructure.instruments import IST, InstrumentStore, expiry_to_date, today_ist
from domains.marketdata.domain.packets import FullPacket, LtpPacket, OptionChainPacket
from domains.marketdata.domain.price_cache import PriceCache, Quote
from shared.contracts.instruments import EXCHANGE_TO_WS_CODE, Instrument

logger = logging.getLogger(__name__)

_DEFAULT_UCC = "PAPER_TRADER"
_DEFAULT_PASSWORD = "paper-password"


class PaperBroker:
    """Simulated 021 broker with realistic portfolio, order execution, and trading state."""

    def __init__(
        self,
        *,
        ucc: str = _DEFAULT_UCC,
        password: str = _DEFAULT_PASSWORD,
        instruments_path: Optional[str] = "data/instruments.csv.gz",
    ):
        self.ucc = ucc
        self.password = password
        self.instruments_path = instruments_path
        self._token_seq = itertools.count(1)
        self._order_seq = itertools.count(1001)
        self._trade_seq = itertools.count(1)
        self.current_token: Optional[str] = None
        self.logins = 0

        # Portfolio state (seeded with realistic Indian equity holdings & intraday positions)
        self.holdings: list[dict] = [
            {
                "isin": "INE002A01018",
                "symbol": "RELIANCE",
                "freeQty": 15,
                "btstQty": 0,
                "sellQty": 0,
                "price": 278000,   # avg purchase Rs 2,780.00
                "prevClose": 280000,
            },
            {
                "isin": "INE009A01021",
                "symbol": "INFY",
                "freeQty": 25,
                "btstQty": 0,
                "sellQty": 0,
                "price": 150000,   # avg purchase Rs 1,500.00
                "prevClose": 152000,
            },
            {
                "isin": "INE467B01029",
                "symbol": "TCS",
                "freeQty": 10,
                "btstQty": 0,
                "sellQty": 0,
                "price": 345000,   # avg purchase Rs 3,450.00
                "prevClose": 350000,
            },
            {
                "isin": "INE040A01034",
                "symbol": "HDFCBANK",
                "freeQty": 30,
                "btstQty": 0,
                "sellQty": 0,
                "price": 162000,   # avg purchase Rs 1,620.00
                "prevClose": 164000,
            },
            {
                "isin": "INE101A01026",
                "symbol": "M&M",
                "freeQty": 10,
                "btstQty": 0,
                "sellQty": 0,
                "price": 290000,   # avg purchase Rs 2,900.00
                "prevClose": 292000,
            },
        ]

        self.positions: list[dict] = [
            {
                "exchange": "NSECM",
                "token": 2885,     # RELIANCE
                "product": "INTRADAY",
                "netQuantity": 10,
                "netPrice": 280500,
                "carryForwardQuantity": 0,
                "buyPrice": 280500,
                "sellPrice": 0,
                "prevClose": 280000,
                "squareOffQuantity": -10,
            },
            {
                "exchange": "NSECM",
                "token": 11536,    # TCS (short)
                "product": "INTRADAY",
                "netQuantity": -5,
                "netPrice": 352000,
                "carryForwardQuantity": 0,
                "buyPrice": 0,
                "sellPrice": 352000,
                "prevClose": 350000,
                "squareOffQuantity": 5,
            },
        ]

        self.trades: list[dict] = [
            {
                "tradeId": next(self._trade_seq),
                "orderId": 991,
                "tradeTime": int(time.time()) - 3600,
                "quantity": 10,
                "token": 2885,
                "exchange": "NSECM",
                "product": "INTRADAY",
                "price": 280500,
            },
            {
                "tradeId": next(self._trade_seq),
                "orderId": 992,
                "tradeTime": int(time.time()) - 1800,
                "quantity": -5,
                "token": 11536,
                "exchange": "NSECM",
                "product": "INTRADAY",
                "price": 352000,
            },
        ]

        self.orders: list[dict] = []
        self._price_lookup: Optional[Callable[[str, int], int]] = None
        self._on_order_update: Optional[Callable[[dict], Any]] = None

    def set_price_lookup(self, fn: Callable[[str, int], int]) -> None:
        self._price_lookup = fn

    def set_order_listener(self, fn: Callable[[dict], Any]) -> None:
        self._on_order_update = fn

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    @staticmethod
    def _envelope(data=None, *, success: bool = True, error: Optional[str] = None) -> dict:
        return {"data": data, "success": success, "error": error}

    def _json(self, status: int, payload, headers: Optional[dict] = None) -> httpx.Response:
        return httpx.Response(
            status,
            content=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", **(headers or {})},
        )

    def _book_and_fill(self, body: dict) -> dict:
        order_id = next(self._order_seq)
        now = int(time.time())
        token = int(body.get("token", 0))
        exchange = {"NSE": "NSECM", "BSE": "BSEEQ", "BSEFO": "BSEEQD"}.get(body.get("exchange"), body.get("exchange"))
        qty = int(body.get("qty", 0))
        requested_price = int(body.get("price", 0))
        is_market = requested_price == 0

        # Reference price from price cache or requested price
        fill_price = requested_price
        if is_market and self._price_lookup:
            fill_price = self._price_lookup(exchange, token) or 250000

        order = {
            "orderId": order_id,
            "time": now,
            "lastActivity": now,
            "token": token,
            "exchange": exchange,
            "product": body.get("product", "CNC"),
            "qtyRemaining": 0 if is_market else qty,
            "qtyTraded": qty if is_market else 0,
            "discQty": 0,
            "price": fill_price,
            "triggerPrice": int(body.get("trigger", 0)),
            "book": body.get("book", "RL"),
            "validity": body.get("validity", "Day"),
            "status": "Executed" if is_market else ("AcceptedForAMO" if body.get("amo") else "Pending"),
            "reason": "",
            "placedBy": "User",
            "amo": bool(body.get("amo")),
            "exchangeOrderNumber": f"EXCH-{order_id}",
        }
        self.orders.insert(0, order)

        if is_market:
            # Record execution trade
            trade_id = next(self._trade_seq)
            sign = 1 if body.get("book") == "RL" and not body.get("amo") else 1
            # Check side if available
            side = body.get("side") or ("BUY" if qty > 0 else "SELL")
            trade_sign = 1 if side == "BUY" else -1
            self.trades.append({
                "tradeId": trade_id,
                "orderId": order_id,
                "tradeTime": now,
                "quantity": trade_sign * qty,
                "token": token,
                "exchange": exchange,
                "product": body.get("product"),
                "price": fill_price,
            })
            self._update_portfolio_on_fill(exchange, token, body.get("product"), side, qty, fill_price)

        if self._on_order_update:
            try:
                self._on_order_update(order)
            except Exception as exc:
                logger.debug("Order update listener failed: %s", exc)

        return order

    def _update_portfolio_on_fill(self, exchange: str, token: int, product: str, side: str, qty: int, price: int) -> None:
        if product == "CNC":
            for h in self.holdings:
                if h.get("exchange") == exchange and h.get("token") == token:
                    if side == "BUY":
                        h["freeQty"] += qty
                    elif side == "SELL":
                        h["freeQty"] = max(0, h["freeQty"] - qty)
                    return
            if side == "BUY":
                self.holdings.append({
                    "isin": f"INE{token:09d}",
                    "symbol": f"TOKEN_{token}",
                    "freeQty": qty,
                    "btstQty": 0,
                    "sellQty": 0,
                    "price": price,
                    "prevClose": price,
                })
        else:
            for p in self.positions:
                if str(p.get("exchange")) == exchange and int(p.get("token", 0)) == token and p.get("product") == product:
                    curr_qty = int(p.get("netQuantity", 0))
                    delta = qty if side == "BUY" else -qty
                    new_qty = curr_qty + delta
                    p["netQuantity"] = new_qty
                    p["squareOffQuantity"] = -new_qty
                    if side == "BUY":
                        p["buyPrice"] = price
                    else:
                        p["sellPrice"] = price
                    return
            delta = qty if side == "BUY" else -qty
            self.positions.append({
                "exchange": exchange,
                "token": token,
                "product": product,
                "netQuantity": delta,
                "netPrice": price,
                "carryForwardQuantity": 0,
                "buyPrice": price if side == "BUY" else 0,
                "sellPrice": price if side == "SELL" else 0,
                "prevClose": price,
                "squareOffQuantity": -delta,
            })

    async def _handle(self, request: httpx.Request) -> httpx.Response:
        method = request.method
        prefix = "/api/developer-api/v1"
        path = request.url.path[len(prefix):] if request.url.path.startswith(prefix) else request.url.path
        body = json.loads(request.content) if request.content else {}

        # ── Auth ──
        if path == "/auth/token" and method == "POST":
            self.logins += 1
            self.current_token = f"paper-token-{next(self._token_seq)}"
            data = {
                "accessToken": self.current_token,
                "tokenType": "Bearer",
                "expiresAt": "2099-01-01T05:00:00+05:30",
                "expiresIn": 86400 * 365,
                "ucc": self.ucc,
            }
            return self._json(200, self._envelope(data))

        # Check authorization
        auth = request.headers.get("Authorization", "")
        if not self.current_token or not auth.startswith("Bearer "):
            # For paper mode, accept if unauthenticated or generate new
            pass

        # ── GET endpoints ──
        if method == "GET":
            if path == "/portfolio/positions":
                return self._json(200, self.positions)
            if path == "/portfolio/holdings":
                return self._json(200, self.holdings)
            if path == "/orders":
                return self._json(200, self.orders)
            if path == "/trades":
                return self._json(200, self.trades)
            if path == "/websocket/ephemeral-key":
                return self._json(200, self._envelope({"token": f"paper-eph-{next(self._token_seq)}"}))
            if path == "/instruments":
                if self.instruments_path and Path(self.instruments_path).is_file():
                    content = Path(self.instruments_path).read_bytes()
                    return httpx.Response(200, content=content, headers={"Content-Type": "application/gzip"})
                return httpx.Response(200, content=gzip.compress(b"token,exchange\n"), headers={"Content-Type": "application/gzip"})
            if path.startswith("/orders/") and path.endswith("/trades"):
                oid = path.split("/")[2]
                return self._json(200, [t for t in self.trades if str(t.get("orderId")) == oid])
            if path.startswith("/orders/"):
                oid = path.split("/")[2]
                rows = [o for o in self.orders if str(o["orderId"]) == oid]
                if not rows:
                    return self._json(404, self._envelope(None, success=False, error="Order not found"))
                return self._json(200, rows)

        # ── POST /orders ──
        if path == "/orders" and method == "POST":
            order = self._book_and_fill(body)
            return self._json(200, self._envelope({
                "type": "SUCCESS",
                "message": "Order placed successfully (Paper Trading)",
                "orderId": str(order["orderId"]),
            }))

        # ── PUT/DELETE /orders ──
        if path.startswith("/orders/") and method in ("PUT", "DELETE"):
            oid = path.split("/")[2]
            rows = [o for o in self.orders if str(o["orderId"]) == oid]
            if not rows:
                return self._json(400, self._envelope(None, success=False, error="Invalid order id"))
            order = rows[0]
            if method == "DELETE":
                order["status"] = "Cancelled"
            else:
                order.update({
                    "price": body.get("price", order["price"]),
                    "triggerPrice": body.get("trigger", order["triggerPrice"]),
                    "qtyRemaining": body.get("qty", order["qtyRemaining"]),
                })
            return self._json(200, self._envelope({"type": "SUCCESS", "message": "ok"}))

        return self._json(400, self._envelope(None, success=False, error=f"Unknown route {method} {path}"))


class PaperMarketSocket:
    """Simulated market data feed that keeps PriceCache continuously fresh with live-like prices."""

    def __init__(self, cache: PriceCache, instruments: InstrumentStore, paper_broker: Optional[PaperBroker] = None):
        self.cache = cache
        self.instruments = instruments
        self.paper_broker = paper_broker
        self._subs: dict[tuple[int, int], str] = {}  # key -> mode
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self.connect_count = 1
        self.silent: set[tuple[int, int]] = set()
        self.last_error: Optional[str] = None

        # Pre-seed benchmark equity & index prices in paise
        self._known_prices: dict[tuple[int, int], int] = {
            (1, 2885): 281000,    # RELIANCE Rs 2,810.00
            (1, 1594): 153500,    # INFY Rs 1,535.00
            (1, 11536): 348000,   # TCS Rs 3,480.00
            (1, 1333): 163500,    # HDFCBANK Rs 1,635.00
            (1, 2031): 288000,    # M&M Rs 2,880.00
            (1, 467): 72000,      # HDFCLIFE Rs 720.00
            (3, 26000): 2452000,  # NIFTY index 24,520.00
            (3, 26009): 5215000,  # BANKNIFTY index 52,150.00
        }

        if self.paper_broker:
            self.paper_broker.set_price_lookup(self._get_price_for_broker)

        self._seed_initial_cache()

    @property
    def connected(self) -> bool:
        return True

    def subscription_count(self) -> int:
        return len(self._subs)

    def _get_price_for_broker(self, exchange: str, token: int) -> int:
        code = EXCHANGE_TO_WS_CODE.get(exchange, 1)
        quote = self.cache.get(code, token)
        if quote and quote.ltp:
            return quote.ltp
        return self._known_prices.get((code, token), 250000)

    def _seed_initial_cache(self) -> None:
        self.cache.on_connected()
        for (code, token), ltp in self._known_prices.items():
            prev_close = ltp - random.randint(-1000, 1000)
            self.cache.apply(LtpPacket(code, token, ltp, prev_close=prev_close))
        self._seed_nifty_options(2452000)

    def _seed_nifty_options(self, spot: int) -> None:
        """Seed strikes around ATM for NIFTY options so option chain queries work out of the box."""
        atm = (spot // 5000) * 5000
        today = today_ist()
        expiry = self.instruments.nearest_expiry("NIFTY", today=today) or 0
        nifty_options = [o for o in self.instruments.options("NIFTY") if not expiry or o.expiry == expiry]

        for opt in nifty_options:
            diff = opt.strike_price - spot
            intrinsic = max(0, -diff if opt.option_type == "PUT" else diff)
            time_value = max(2500, int(35000 * math.exp(-abs(diff) / 100000)))
            opt_price = max(50, intrinsic + time_value)
            delta = 0.5 + (0.5 if opt.option_type == "CALL" else -0.5) * (1.0 / (1.0 + math.exp(-diff / 30000)))
            if opt.option_type == "PUT":
                delta = delta - 1.0

            self.cache.apply(OptionChainPacket(
                exchange_code=opt.ws_code,
                token=opt.token,
                ltp=opt_price,
                oi=random.randint(50000, 2000000),
                iv=0.145,
                greeks={"delta": round(delta, 4)},
            ))

    async def ensure(self, keys: Iterable[tuple[int, int]], mode: str = "ltp", *, pinned: bool = False) -> list[tuple[int, int]]:
        wanted = list(keys)
        for key in wanted:
            self._subs[key] = mode
            if self.cache.get(*key) is None:
                # Generate realistic initial quote
                inst = self.instruments.get_by_ws(key[0], key[1])
                price = 250000
                if inst:
                    if inst.lower_circuit and inst.upper_circuit:
                        price = (inst.lower_circuit + inst.upper_circuit) // 2
                    elif inst.strike_price:
                        price = max(100, abs(2450000 - inst.strike_price) // 2)
                self.cache.apply(LtpPacket(key[0], key[1], price, prev_close=price))
        return wanted

    async def release(self, keys: Iterable[tuple[int, int]]) -> None:
        for k in keys:
            self._subs.pop(k, None)

    async def wait_fresh(self, keys: Iterable[tuple[int, int]], timeout: float = 2.5) -> set[tuple[int, int]]:
        self.cache.on_frame()
        return set(keys)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._running = True
            self._task = asyncio.create_task(self._tick_loop(), name="paper-market-ticks")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    async def _tick_loop(self) -> None:
        """Periodically touches cache.on_frame() and adds mild price random-walk so quotes stay alive."""
        while self._running:
            try:
                self.cache.on_frame()
                for key in list(self._subs):
                    quote = self.cache.get(*key)
                    if quote and quote.ltp:
                        # Mild tick wiggle: ±0.05%
                        tick = random.choice([-10, 0, 10, 20, -20])
                        new_ltp = max(50, quote.ltp + tick)
                        self.cache.apply(LtpPacket(key[0], key[1], new_ltp, prev_close=quote.prev_close))
                await asyncio.sleep(2.0)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("Paper market tick error: %s", exc)
                await asyncio.sleep(2.0)

