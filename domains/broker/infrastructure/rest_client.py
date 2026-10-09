"""
021 Trade REST client.

Rules this file enforces:
- One shared httpx client with explicit timeouts; every call passes the token-bucket limiter.
- Reads (GET) retry on 429/500/503/timeouts with exponential backoff + full jitter, max N times.
- Order actions (POST/PUT/DELETE /orders) are NEVER retried. A lost response becomes
  BrokerOutcomeUnknownError so the caller reconciles via GET /orders instead of resending.
- 401 triggers a single-flight re-login. A read is replayed once; an order action is not
  replayed (a 401 means 021 did not process it) and the caller is told it was not sent.
- Responses use 021's envelope {data, success, error}; list endpoints return bare arrays.
"""
import asyncio
import gzip
import logging
import random
import time
from typing import Any, Awaitable, Callable, Optional

import httpx

from domains.broker.domain.errors import (
    BrokerAuthError,
    BrokerError,
    BrokerNotFoundError,
    BrokerOutcomeUnknownError,
    BrokerRateLimitedError,
    BrokerRejectedError,
    BrokerTimeoutError,
    BrokerUnavailableError,
    error_for_status,
)
from domains.broker.infrastructure.rate_limiter import TokenBucket
from domains.broker.infrastructure.token_manager import TokenManager
from shared.contracts.orders import OrderPayload

logger = logging.getLogger(__name__)

AuditFn = Callable[[dict], Awaitable[None] | None]

_MAX_ERROR_TEXT = 300
# Errors raised before any bytes could reach 021: safe to call "not sent".
_NOT_SENT_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
# Errors after the request may have been delivered: outcome unknown for order actions.
_MAYBE_SENT_ERRORS = (httpx.ReadTimeout, httpx.WriteTimeout, httpx.ReadError, httpx.WriteError, httpx.RemoteProtocolError)


def _clean_text(value: Any) -> str:
    """021 text (rejection reasons etc.) is untrusted: strip control chars and bound its length."""
    text = "" if value is None else str(value)
    text = "".join(ch for ch in text if ch.isprintable())
    return text[:_MAX_ERROR_TEXT]


class TradeRestClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        timeout_seconds: float = 10.0,
        rate_per_second: float = 5.0,
        max_get_retries: int = 3,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
        rng: Callable[[], float] = random.random,
        audit: Optional[AuditFn] = None,
    ):
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout_seconds, connect=min(5.0, timeout_seconds)),
            transport=transport,
            headers={"Accept": "application/json"},
        )
        self._sleep = sleep
        self._rng = rng
        self._max_get_retries = max(0, max_get_retries)
        self._limiter = TokenBucket(rate_per_second, burst=max(1, int(rate_per_second)), clock=clock, sleep=sleep)
        self._audit = audit
        self.tokens = TokenManager(username, password, self._login)

    async def aclose(self) -> None:
        await self._http.aclose()

    @property
    def configured(self) -> bool:
        return self.tokens.configured

    # ── Low level ────────────────────────────────────────────────

    def _backoff(self, attempt: int) -> float:
        # Full jitter: uniform in [0, 0.5 * 2^attempt], capped at 8 s.
        return min(8.0, 0.5 * (2 ** attempt)) * self._rng()

    async def _emit_audit(self, event: dict) -> None:
        if self._audit is None:
            return
        try:
            result = self._audit(event)
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:  # auditing must never break trading paths
            logger.warning("audit hook failed: %s", exc)

    async def _raw(
        self,
        method: str,
        path: str,
        *,
        token: Optional[str],
        json_body: Optional[dict],
        is_order_action: bool,
    ) -> httpx.Response:
        await self._limiter.acquire()
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        started = time.monotonic()
        outcome = "ok"
        status: Optional[int] = None
        try:
            response = await self._http.request(method, path, json=json_body, headers=headers)
            status = response.status_code
            return response
        except _NOT_SENT_ERRORS as exc:
            outcome = "not_sent"
            raise BrokerUnavailableError(f"Could not connect to 021 ({type(exc).__name__}); request not sent", path=path) from exc
        except _MAYBE_SENT_ERRORS as exc:
            outcome = "unknown" if is_order_action else "timeout"
            if is_order_action:
                raise BrokerOutcomeUnknownError(f"No response from 021 for {method} {path} ({type(exc).__name__})", path=path) from exc
            raise BrokerTimeoutError(f"021 did not respond in time ({type(exc).__name__})", path=path) from exc
        except httpx.TimeoutException as exc:
            outcome = "unknown" if is_order_action else "timeout"
            if is_order_action:
                raise BrokerOutcomeUnknownError(f"Timed out waiting for 021 on {method} {path}", path=path) from exc
            raise BrokerTimeoutError("021 did not respond in time", path=path) from exc
        finally:
            await self._emit_audit({
                "kind": "021_http",
                "method": method,
                "path": path,
                "status": status,
                "outcome": outcome,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "order_action": is_order_action,
            })

    def _parse(self, response: httpx.Response, path: str, *, is_order_action: bool, want_bytes: bool) -> Any:
        status = response.status_code
        body: Any = None
        if not want_bytes or status >= 400:
            try:
                body = response.json()
            except ValueError:
                body = None

        if 200 <= status < 300:
            if want_bytes:
                content = response.content
                if content[:2] == b"\x1f\x8b":
                    content = gzip.decompress(content)
                return content
            if isinstance(body, dict) and "success" in body:
                if body.get("success"):
                    return body.get("data")
                message = _clean_text(body.get("error")) or "021 reported failure"
                if is_order_action:
                    raise BrokerRejectedError(message, status=status, path=path)
                raise BrokerUnavailableError(message, status=status, path=path)
            if body is None:
                raise BrokerUnavailableError("021 returned a non-JSON response", status=status, path=path)
            return body

        message = _clean_text(body.get("error")) if isinstance(body, dict) else ""
        if is_order_action and status >= 500 and not (status == 500 and message):
            # Gateway errors on an order action do not prove the order was not placed.
            raise BrokerOutcomeUnknownError(f"021 returned HTTP {status} for an order action", status=status, path=path)
        error = error_for_status(status, message, path=path, is_order_action=is_order_action)
        if isinstance(error, BrokerRateLimitedError):
            retry_after = response.headers.get("Retry-After")
            try:
                error.retry_after = float(retry_after) if retry_after else None
            except ValueError:
                error.retry_after = None
        raise error

    async def _call_once(self, method: str, path: str, *, json_body: Optional[dict], is_order_action: bool, want_bytes: bool) -> Any:
        token = await self.tokens.get_token()
        response = await self._raw(method, path, token=token, json_body=json_body, is_order_action=is_order_action)
        if response.status_code == 401:
            new_token = await self.tokens.refresh_after_401(token)
            if is_order_action:
                raise BrokerAuthError(
                    "The 021 session had been replaced (another login with this UCC) and was renewed; the order was NOT sent.",
                    status=401,
                    path=path,
                )
            response = await self._raw(method, path, token=new_token, json_body=json_body, is_order_action=False)
        return self._parse(response, path, is_order_action=is_order_action, want_bytes=want_bytes)

    async def _read(self, path: str, *, want_bytes: bool = False) -> Any:
        attempt = 0
        while True:
            try:
                return await self._call_once("GET", path, json_body=None, is_order_action=False, want_bytes=want_bytes)
            except BrokerError as exc:
                if not exc.retryable or attempt >= self._max_get_retries:
                    raise
                delay = self._backoff(attempt)
                if isinstance(exc, BrokerRateLimitedError):
                    delay = max(delay, exc.retry_after or 1.0)
                    self._limiter.penalize(delay)
                logger.info("021 GET %s failed (%s); retry %d/%d in %.2fs", path, type(exc).__name__, attempt + 1, self._max_get_retries, delay)
                attempt += 1
                await self._sleep(delay)

    async def _order_action(self, method: str, path: str, body: dict) -> Any:
        # Exactly one attempt. Callers must reconcile BrokerOutcomeUnknownError via GET /orders.
        return await self._call_once(method, path, json_body=body, is_order_action=True, want_bytes=False)

    async def _login(self, username: str, password: str) -> dict:
        attempt = 0
        while True:
            try:
                response = await self._raw(
                    "POST", "/auth/token", token=None,
                    json_body={"username": username, "password": password},
                    is_order_action=False,
                )
                if response.status_code == 401:
                    raise BrokerAuthError("021 rejected the UCC or password", status=401, path="/auth/token")
                data = self._parse(response, "/auth/token", is_order_action=False, want_bytes=False)
                if not isinstance(data, dict):
                    raise BrokerUnavailableError("Unexpected 021 login response", path="/auth/token")
                return data
            except BrokerError as exc:
                if not exc.retryable or attempt >= self._max_get_retries:
                    raise
                delay = self._backoff(attempt)
                if isinstance(exc, BrokerRateLimitedError):
                    delay = max(delay, exc.retry_after or 1.0)
                attempt += 1
                await self._sleep(delay)

    # ── Reads ────────────────────────────────────────────────────

    async def get_positions(self) -> list[dict]:
        return list(await self._read("/portfolio/positions") or [])

    async def get_holdings(self) -> list[dict]:
        return list(await self._read("/portfolio/holdings") or [])

    async def get_orders(self) -> list[dict]:
        return list(await self._read("/orders") or [])

    async def get_order(self, order_id: str) -> Optional[dict]:
        try:
            rows = await self._read(f"/orders/{order_id}")
        except BrokerNotFoundError:
            return None
        if isinstance(rows, list):
            return rows[0] if rows else None
        return rows

    async def get_trades(self) -> list[dict]:
        return list(await self._read("/trades") or [])

    async def get_order_trades(self, order_id: str) -> list[dict]:
        return list(await self._read(f"/orders/{order_id}/trades") or [])

    async def get_ephemeral_key(self) -> str:
        data = await self._read("/websocket/ephemeral-key")
        key = data.get("token") if isinstance(data, dict) else None
        if not key:
            raise BrokerUnavailableError("021 returned no websocket key", path="/websocket/ephemeral-key")
        return key

    async def download_instruments(self) -> bytes:
        return await self._read("/instruments", want_bytes=True)

    # ── Order actions (only the execution service may call these, from Phase 2) ──

    async def place_order(self, payload: OrderPayload) -> str:
        data = await self._order_action("POST", "/orders", payload.to_request_json())
        order_id = data.get("orderId") if isinstance(data, dict) else None
        if order_id is None:
            raise BrokerOutcomeUnknownError("021 accepted the request but returned no orderId", path="/orders")
        return str(order_id)

    async def modify_order(self, order_id: str, payload: OrderPayload) -> dict:
        return await self._order_action("PUT", f"/orders/{order_id}", payload.to_request_json()) or {}

    async def cancel_order(self, order_id: str, *, exchange: str, token: int, product: str) -> dict:
        body = {"exchange": exchange, "token": token, "product": product}
        return await self._order_action("DELETE", f"/orders/{order_id}", body) or {}
