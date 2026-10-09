"""
Fault-injecting fake of the 021 Trade REST API, served through httpx.MockTransport.

Use it to prove behaviour under the sandbox's deliberate failures:
    fake = Fake021()
    fake.fail_next("/portfolio/positions", status=503, count=2)       # two 503s, then success
    fake.fail_next("/orders", method="POST", exc=httpx.ReadTimeout, accept_first=True)  # timeout AFTER the order was booked
    fake.random_fault_rate = 0.3                                       # 30% of calls get 500/503/429
    fake.revoke_token()                                                # simulate another login elsewhere
    fake.order_fault_rate = 0.4                                        # 40% of order POSTs hit a random send fault
    fake.fill(order_id, qty, price)                                    # simulate an exchange fill
"""
import gzip
import itertools
import json
import random
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

import httpx

BASE_URL = "https://fake021.test/api/developer-api/v1"
_PREFIX = "/api/developer-api/v1"


@dataclass
class FaultRule:
    path: str
    method: Optional[str]
    status: Optional[int]
    error: str
    exc: Optional[type]
    accept_first: bool
    remaining: int
    headers: dict
    body: Optional[bytes]


class Fake021:
    def __init__(self, *, ucc: str = "HACK0001", password: str = "test-password", seed: int = 7):
        self.ucc = ucc
        self.password = password
        self.current_token: Optional[str] = None
        self.logins = 0
        self._token_seq = itertools.count(1)
        self._order_seq = itertools.count(1001)
        self.positions: list[dict] = []
        self.holdings: list[dict] = []
        self.trades: list[dict] = []
        self.orders: list[dict] = []
        self.instruments_csv: str = ""
        self.rules: deque[FaultRule] = deque()
        self.random_fault_rate = 0.0
        self.random_statuses = (500, 503, 429)
        self.rng = random.Random(seed)
        self.requests: list[tuple[str, str]] = []
        self.order_bodies: list[dict] = []        # every POST /orders body 021 actually booked
        self.order_fault_rate = 0.0
        # timeout after booking / timeout before booking / 503 without booking / risk rejection
        self.order_fault_modes = ("timeout_after_accept", "timeout_before_accept", "gateway_503", "risk_reject")
        self.fault_log: list[str] = []

    # ── wiring ──
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def count(self, method: str, path: str) -> int:
        return sum(1 for m, p in self.requests if m == method and p == path)

    # ── fault controls ──
    def fail_next(
        self,
        path: str,
        *,
        status: Optional[int] = None,
        count: int = 1,
        method: Optional[str] = None,
        error: str = "",
        exc: Optional[type] = None,
        accept_first: bool = False,
        headers: Optional[dict] = None,
        body: Optional[bytes] = None,
    ) -> None:
        self.rules.append(FaultRule(path, method, status, error, exc, accept_first, count, headers or {}, body))

    def revoke_token(self) -> None:
        """Another login elsewhere: the current token stops working immediately."""
        self.current_token = f"revoked-by-other-login-{next(self._token_seq)}"

    # ── helpers ──
    @staticmethod
    def _envelope(data=None, *, success: bool = True, error: Optional[str] = None) -> dict:
        return {"data": data, "success": success, "error": error}

    def _json(self, status: int, payload, headers: Optional[dict] = None) -> httpx.Response:
        return httpx.Response(status, content=json.dumps(payload).encode(), headers={"Content-Type": "application/json", **(headers or {})})

    def _match_rule(self, method: str, path: str) -> Optional[FaultRule]:
        for rule in list(self.rules):
            if path == rule.path and (rule.method is None or rule.method == method):
                rule.remaining -= 1
                if rule.remaining <= 0:
                    self.rules.remove(rule)
                return rule
        return None

    def _book_order(self, body: dict) -> dict:
        order_id = next(self._order_seq)
        now = int(time.time())
        order = {
            "orderId": order_id, "time": now, "lastActivity": now,
            "token": body.get("token"), "exchange": {"NSE": "NSECM", "BSE": "BSEEQ", "BSEFO": "BSEEQD"}.get(body.get("exchange"), body.get("exchange")),
            "product": body.get("product"), "qtyRemaining": body.get("qty"), "qtyTraded": 0, "discQty": 0,
            "price": body.get("price"), "triggerPrice": body.get("trigger", 0), "book": body.get("book"),
            "validity": body.get("validity"), "status": "AcceptedForAMO" if body.get("amo") else "Pending", "reason": "",
            "placedBy": "User", "amo": bool(body.get("amo")), "exchangeOrderNumber": "",
        }
        self.orders.insert(0, order)
        self.order_bodies.append(dict(body))
        return order

    def fill(self, order_id, qty: int, price: int) -> None:
        """Simulate an exchange fill of `qty` (absolute) at `price` paise."""
        order = next(o for o in self.orders if str(o["orderId"]) == str(order_id))
        sign = 1 if order["qtyRemaining"] > 0 else -1
        order["qtyTraded"] += qty
        order["qtyRemaining"] -= sign * qty
        order["status"] = "Executed" if order["qtyRemaining"] == 0 else "Pending"
        self.trades.append({"tradeId": len(self.trades) + 1, "orderId": order["orderId"], "tradeTime": int(time.time()),
                            "quantity": sign * qty, "token": order["token"], "exchange": order["exchange"],
                            "product": order["product"], "price": price})

    # ── request handling ──
    async def _handle(self, request: httpx.Request) -> httpx.Response:
        method = request.method
        path = request.url.path[len(_PREFIX):] if request.url.path.startswith(_PREFIX) else request.url.path
        self.requests.append((method, path))
        body = json.loads(request.content) if request.content else {}

        rule = self._match_rule(method, path)
        if rule is not None:
            if rule.accept_first and method == "POST" and path == "/orders":
                self._book_order(body)
            if rule.exc is not None:
                raise rule.exc("injected fault", request=request)
            if rule.body is not None:
                return httpx.Response(rule.status or 500, content=rule.body, headers=rule.headers)
            return self._json(rule.status or 500, self._envelope(None, success=False, error=rule.error or "injected"), rule.headers)

        if self.random_fault_rate and path != "/auth/token" and self.rng.random() < self.random_fault_rate:
            status = self.rng.choice(self.random_statuses)
            headers = {"Retry-After": "0"} if status == 429 else {}
            return self._json(status, self._envelope(None, success=False, error="Service temporarily unavailable"), headers)

        if path == "/auth/token" and method == "POST":
            if body.get("username") != self.ucc or body.get("password") != self.password:
                return self._json(401, self._envelope(None, success=False, error="Invalid username or password"))
            self.logins += 1
            self.current_token = f"token-{next(self._token_seq)}"
            data = {"accessToken": self.current_token, "tokenType": "Bearer", "expiresAt": "2099-01-01T05:00:00+05:30", "expiresIn": 39600}
            return self._json(200, self._envelope(data))

        auth = request.headers.get("Authorization", "")
        if not self.current_token or auth != f"Bearer {self.current_token}":
            return self._json(401, self._envelope(None, success=False, error="Invalid or expired access token."))

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
                return self._json(200, self._envelope({"token": f"eph-{next(self._token_seq)}"}))
            if path == "/instruments":
                return httpx.Response(200, content=gzip.compress(self.instruments_csv.encode()), headers={"Content-Type": "application/gzip"})
            if path.startswith("/orders/") and path.endswith("/trades"):
                oid = path.split("/")[2]
                return self._json(200, [t for t in self.trades if str(t.get("orderId")) == oid])
            if path.startswith("/orders/"):
                oid = path.split("/")[2]
                rows = [o for o in self.orders if str(o["orderId"]) == oid]
                if not rows:
                    return self._json(404, self._envelope(None, success=False, error="Order not found"))
                return self._json(200, rows)

        if path == "/orders" and method == "POST":
            if self.order_fault_rate and self.rng.random() < self.order_fault_rate:
                mode = self.rng.choice(self.order_fault_modes)
                self.fault_log.append(mode)
                if mode == "timeout_after_accept":
                    self._book_order(body)
                    raise httpx.ReadTimeout("injected: booked, response lost", request=request)
                if mode == "timeout_before_accept":
                    raise httpx.ReadTimeout("injected: request lost", request=request)
                if mode == "gateway_503":
                    return self._json(503, self._envelope(None, success=False, error="Service temporarily unavailable"))
                return self._json(500, self._envelope(None, success=False, error="Insufficient funds"))
            order = self._book_order(body)
            return self._json(200, self._envelope({"type": "SUCCESS", "message": "Order placed successfully", "orderId": str(order["orderId"])}))
        if path.startswith("/orders/") and method in ("PUT", "DELETE"):
            oid = path.split("/")[2]
            rows = [o for o in self.orders if str(o["orderId"]) == oid]
            if not rows:
                return self._json(400, self._envelope(None, success=False, error="Invalid order id"))
            order = rows[0]
            if order["status"] not in ("Pending", "Placed", "Received", "AcceptedForAMO"):
                return self._json(500, self._envelope(None, success=False, error=f"Order is {order['status']}"))
            if method == "DELETE":
                order["status"] = "Cancelled"
            else:
                order.update({"price": body.get("price"), "triggerPrice": body.get("trigger", 0), "qtyRemaining": body.get("qty")})
            return self._json(200, self._envelope({"type": "SUCCESS", "message": "ok"}))

        return self._json(400, self._envelope(None, success=False, error=f"unknown route {method} {path}"))
