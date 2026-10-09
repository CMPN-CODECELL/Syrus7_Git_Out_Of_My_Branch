"""
021 access-token manager.

- One login, one shared token. 021 allows one live token per account: a new login revokes the old.
- Single-flight: concurrent callers that hit 401 with the same token trigger exactly one re-login.
- Proactive refresh shortly before the 5:00 AM IST expiry.
- The password is never logged and never leaves this object.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional

from domains.broker.domain.errors import BrokerAuthError, BrokerNotConfiguredError

logger = logging.getLogger(__name__)

LoginFn = Callable[[str, str], Awaitable[dict]]

_REFRESH_MARGIN = timedelta(minutes=2)


class TokenManager:
    def __init__(
        self,
        username: str,
        password: str,
        login_fn: LoginFn,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self._username = username
        self._password = password
        self._login_fn = login_fn
        self._now = now
        self._token: Optional[str] = None
        self._expires_at: Optional[datetime] = None
        self._lock = asyncio.Lock()
        self.login_count = 0

    def __repr__(self) -> str:  # never expose credentials in reprs / tracebacks
        return f"TokenManager(username={self._username!r}, has_token={self._token is not None})"

    @property
    def configured(self) -> bool:
        return bool(self._username and self._password)

    @property
    def expires_at(self) -> Optional[datetime]:
        return self._expires_at

    def _valid(self) -> bool:
        if not self._token:
            return False
        if self._expires_at is None:
            return True
        return self._now() < self._expires_at - _REFRESH_MARGIN

    async def get_token(self) -> str:
        if self._valid():
            return self._token  # type: ignore[return-value]
        async with self._lock:
            if self._valid():
                return self._token  # type: ignore[return-value]
            return await self._login()

    async def refresh_after_401(self, failed_token: Optional[str]) -> str:
        """Called when a request using `failed_token` got 401. Only the first caller logs in;
        everyone else picks up the token it obtained."""
        async with self._lock:
            if self._token and self._token != failed_token and self._valid():
                return self._token
            self._token = None
            return await self._login()

    async def _login(self) -> str:
        if not self.configured:
            raise BrokerNotConfiguredError("021 credentials are not configured (TRADE_API_USERNAME / TRADE_API_PASSWORD)")
        data = await self._login_fn(self._username, self._password)
        token = data.get("accessToken")
        if not token:
            raise BrokerAuthError("021 login returned no access token")
        self._token = token
        self._expires_at = _parse_expiry(data, self._now())
        self.login_count += 1
        logger.info("021 login ok for %s; token valid until %s", self._username, self._expires_at)
        return token


def _parse_expiry(data: dict, now: datetime) -> Optional[datetime]:
    raw = data.get("expiresAt")
    if raw:
        try:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            pass
    seconds = data.get("expiresIn")
    if isinstance(seconds, (int, float)) and seconds > 0:
        return now + timedelta(seconds=float(seconds))
    return None
