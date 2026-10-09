"""
021 market-data websocket client.

- Fetches a fresh ephemeral key for every connection (keys are only checked at connect).
- Reconnects with exponential backoff + jitter, including the daily 08:00 IST restart, and
  resubscribes everything (021 does not remember subscriptions).
- Enforces the 100-instruments-per-connection cap: pinned instruments (holdings/positions)
  are never evicted; ad-hoc ones (e.g. an option chain someone asked about) are evicted LRU.
- 021 silently ignores bad subscriptions, so a watchdog re-sends any subscription that has
  produced no data, and reports it as silent after repeated attempts.
"""
import asyncio
import json
import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Iterable, Optional

from domains.marketdata.domain.packets import parse_market_frame
from domains.marketdata.domain.price_cache import PriceCache

logger = logging.getLogger(__name__)

MAX_INSTRUMENTS = 100
MAX_MESSAGE_BYTES = 5000
OC_FILTERS = "l,o,v,i,md,g"
WATCHDOG_SECONDS = 10.0
WATCHDOG_MAX_RETRIES = 2
_MODE_RANK = {"ltp": 0, "ltpo": 1, "ltpc": 1, "full": 2, "oc": 3}

Key = tuple[int, int]  # (websocket exchange code, token)
ConnectFn = Callable[[str], Awaitable[Any]]
KeyFn = Callable[[], Awaitable[str]]


@dataclass
class _Sub:
    mode: str
    pinned: bool
    last_requested: float
    sent_at: Optional[float] = None
    retries: int = 0
    seen: bool = False


async def _default_connect(url: str):
    import websockets
    return await websockets.connect(url, max_size=2**22, open_timeout=10, close_timeout=5)


class MarketSocketClient:
    def __init__(
        self,
        ws_base_url: str,
        get_key: KeyFn,
        cache: PriceCache,
        *,
        connect: ConnectFn = _default_connect,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
        rng: Callable[[], float] = random.random,
    ):
        self._url = ws_base_url.rstrip("/") + "/market"
        self._get_key = get_key
        self.cache = cache
        self._connect = connect
        self._sleep = sleep
        self._clock = clock
        self._rng = rng
        self._subs: dict[Key, _Sub] = {}
        self._ws: Any = None
        self._send_lock = asyncio.Lock()
        self._update = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._stopping = False
        self.connect_count = 0
        self.last_error: Optional[str] = None
        self.silent: set[Key] = set()

    # ── lifecycle ──
    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stopping = False
            self._task = asyncio.create_task(self._run(), name="kraken-market-socket")

    async def stop(self) -> None:
        self._stopping = True
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    @property
    def connected(self) -> bool:
        return self.cache.connected

    def subscription_count(self) -> int:
        return len(self._subs)

    # ── subscriptions ──
    async def ensure(self, keys: Iterable[Key], mode: str = "ltp", *, pinned: bool = False) -> list[Key]:
        """Subscribe keys in `mode`. Returns the keys actually subscribed (cap permitting)."""
        now = self._clock()
        wanted = list(dict.fromkeys(keys))
        new_or_changed: list[Key] = []
        accepted: list[Key] = []
        for key in wanted:
            sub = self._subs.get(key)
            if sub is not None:
                sub.last_requested = now
                sub.pinned = sub.pinned or pinned
                # One mode per instrument per connection; only ever upgrade (ltp < ltpo/ltpc < full < oc)
                # so a casual LTP request never drops the prev-close or option-chain fields.
                if _MODE_RANK.get(mode, 0) > _MODE_RANK.get(sub.mode, 0):
                    sub.mode = mode
                    new_or_changed.append(key)
                accepted.append(key)
                continue
            if len(self._subs) >= MAX_INSTRUMENTS and not await self._evict_one(exclude=set(wanted)):
                logger.warning("Market socket at %d-instrument cap; cannot add %s", MAX_INSTRUMENTS, key)
                continue
            self._subs[key] = _Sub(mode=mode, pinned=pinned, last_requested=now)
            new_or_changed.append(key)
            accepted.append(key)
        if new_or_changed and self._ws is not None:
            await self._send_subscribe(new_or_changed)
        return accepted

    async def release(self, keys: Iterable[Key]) -> None:
        """Unpin keys (e.g. a position was closed); they become evictable."""
        for key in keys:
            if key in self._subs:
                self._subs[key].pinned = False

    async def _evict_one(self, *, exclude: set[Key]) -> bool:
        candidates = [(s.last_requested, k) for k, s in self._subs.items() if not s.pinned and k not in exclude]
        if not candidates:
            return False
        _, key = min(candidates)
        sub = self._subs.pop(key)
        if self._ws is not None:
            await self._send_json({"Task": "unsubscribe", "Mode": "oc" if sub.mode == "oc" else "ltp", "Instruments": [list(key)]})
        return True

    async def _send_json(self, message: dict) -> None:
        text = json.dumps(message, separators=(",", ":"))
        if len(text.encode()) > MAX_MESSAGE_BYTES:
            raise ValueError("subscription message exceeds 021's 5,000-byte limit")
        async with self._send_lock:
            if self._ws is not None:
                await self._ws.send(text)

    async def _send_subscribe(self, keys: list[Key]) -> None:
        by_mode: dict[str, list[Key]] = {}
        for key in keys:
            sub = self._subs.get(key)
            if sub is not None:
                by_mode.setdefault(sub.mode, []).append(key)
        now = self._clock()
        for mode, mode_keys in by_mode.items():
            for start in range(0, len(mode_keys), 200):
                chunk = mode_keys[start:start + 200]
                message: dict = {"Task": "subscribe", "Mode": mode, "Instruments": [list(k) for k in chunk]}
                if mode == "oc":
                    message["Filters"] = OC_FILTERS
                await self._send_json(message)
            for key in mode_keys:
                sub = self._subs[key]
                sub.sent_at, sub.seen = now, False

    async def wait_fresh(self, keys: Iterable[Key], timeout: float) -> set[Key]:
        """Wait until each key has data from the current connection newer than now, or timeout.
        Returns the keys that are fresh."""
        keys = list(keys)
        since = datetime.now(timezone.utc)
        deadline = self._clock() + timeout
        while True:
            fresh = {k for k in keys if self.cache.fresh_since(k[0], k[1], since) or self._has_current(k)}
            if len(fresh) == len(keys) or self._clock() >= deadline:
                return fresh
            self._update.clear()
            try:
                await asyncio.wait_for(self._update.wait(), timeout=max(0.05, deadline - self._clock()))
            except asyncio.TimeoutError:
                pass

    def _has_current(self, key: Key) -> bool:
        sub = self._subs.get(key)
        return bool(sub and sub.seen) and not self.cache.is_stale(self.cache.get(*key))

    # ── connection loop ──
    async def _run(self) -> None:
        backoff = 1.0
        while not self._stopping:
            started = self._clock()
            try:
                key = await self._get_key()
                self._ws = await self._connect(f"{self._url}?token={key}")
                self.connect_count += 1
                self.cache.on_connected()
                self.last_error = None
                logger.info("Market socket connected (#%d); resubscribing %d instruments", self.connect_count, len(self._subs))
                for sub in self._subs.values():
                    sub.retries = 0
                if self._subs:
                    await self._send_subscribe(list(self._subs))
                await self._read_loop()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"[:200]
                logger.warning("Market socket error: %s", self.last_error)
            finally:
                self.cache.on_disconnected()
                ws, self._ws = self._ws, None
                if ws is not None:
                    try:
                        await ws.close()
                    except Exception:
                        pass
                self._update.set()
            if self._stopping:
                break
            if self._clock() - started > 60:
                backoff = 1.0
            delay = backoff * (0.5 + self._rng())
            backoff = min(backoff * 2, 30.0)
            await self._sleep(delay)

    async def _read_loop(self) -> None:
        watchdog = asyncio.create_task(self._watchdog())
        try:
            async for message in self._ws:
                if isinstance(message, str):
                    continue  # 021 sends binary frames only
                self.cache.on_frame()
                result = parse_market_frame(message)
                for packet in result.packets:
                    self.cache.apply(packet)
                    sub = self._subs.get((packet.exchange_code, packet.token))
                    if sub is not None:
                        sub.seen = True
                        self.silent.discard((packet.exchange_code, packet.token))
                if result.error:
                    logger.warning("Market frame partially parsed (%s); %d bytes skipped", result.error, result.unparsed_bytes)
                self._update.set()
        finally:
            watchdog.cancel()

    async def _watchdog(self) -> None:
        while True:
            await self._sleep(WATCHDOG_SECONDS / 2)
            now = self._clock()
            resend: list[Key] = []
            for key, sub in self._subs.items():
                if sub.seen or sub.sent_at is None or now - sub.sent_at < WATCHDOG_SECONDS:
                    continue
                if sub.retries >= WATCHDOG_MAX_RETRIES:
                    if key not in self.silent:
                        logger.warning("No data for %s after %d subscribe attempts; marking silent", key, sub.retries + 1)
                        self.silent.add(key)
                    continue
                sub.retries += 1
                resend.append(key)
            if resend and self._ws is not None:
                logger.info("Watchdog re-subscribing %d silent instruments", len(resend))
                await self._send_subscribe(resend)
