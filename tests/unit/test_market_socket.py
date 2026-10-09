"""Market socket client: subscribe on connect, reconnect with a fresh key, resubscribe, cap."""
import asyncio
import json

from domains.marketdata.domain.price_cache import PriceCache
from domains.marketdata.infrastructure.market_socket import MAX_INSTRUMENTS, MarketSocketClient
from tests.fakes.market import ltp_packet


class FakeWS:
    def __init__(self, frames: list[bytes], *, drop_after: bool = True):
        self.sent: list[dict] = []
        self._queue: asyncio.Queue = asyncio.Queue()
        for frame in frames:
            self._queue.put_nowait(frame)
        if drop_after:
            self._queue.put_nowait(None)
        self.closed = False

    async def send(self, text: str) -> None:
        self.sent.append(json.loads(text))

    def push(self, frame: bytes) -> None:
        self._queue.put_nowait(frame)

    def __aiter__(self):
        return self

    async def __anext__(self):
        item = await self._queue.get()
        if item is None:
            raise StopAsyncIteration  # server closed the socket (e.g. 08:00 IST restart)
        return item

    async def close(self) -> None:
        self.closed = True


async def test_reconnects_with_new_key_and_resubscribes():
    keys = iter(["key-1", "key-2", "key-3"])
    urls: list[str] = []
    sockets = [FakeWS([ltp_packet(1, 2885, 140000)]), FakeWS([ltp_packet(1, 2885, 140500)], drop_after=False)]

    async def get_key():
        return next(keys)

    async def connect(url):
        urls.append(url)
        return sockets[len(urls) - 1]

    async def no_sleep(_):
        await asyncio.sleep(0)

    cache = PriceCache()
    client = MarketSocketClient("wss://x/api/developer/websocket", get_key, cache, connect=connect, sleep=no_sleep)
    await client.ensure([(1, 2885)], "ltpc", pinned=True)
    client.start()
    for _ in range(200):
        await asyncio.sleep(0)
        if client.connect_count == 2 and cache.get(1, 2885) and cache.get(1, 2885).ltp == 140500:
            break
    await client.stop()

    assert urls == ["wss://x/api/developer/websocket/market?token=key-1", "wss://x/api/developer/websocket/market?token=key-2"]
    for ws in sockets:  # every connection re-sent the subscription (021 forgets them)
        assert ws.sent[0] == {"Task": "subscribe", "Mode": "ltpc", "Instruments": [[1, 2885]]}
    assert cache.get(1, 2885).ltp == 140500


async def test_quote_is_stale_until_refreshed_on_new_connection():
    cache = PriceCache()
    cache.on_connected()
    from domains.marketdata.domain.packets import LtpPacket

    quote = cache.apply(LtpPacket(1, 2885, 100))
    assert not cache.is_stale(quote)
    cache.on_disconnected()
    assert cache.is_stale(quote)
    cache.on_connected()
    assert cache.is_stale(cache.get(1, 2885))  # from the previous connection
    cache.apply(LtpPacket(1, 2885, 101))
    assert not cache.is_stale(cache.get(1, 2885))


async def test_instrument_cap_evicts_unpinned_lru_and_never_pinned():
    async def get_key():
        return "k"

    client = MarketSocketClient("wss://x", get_key, PriceCache())
    pinned = [(1, i) for i in range(MAX_INSTRUMENTS - 2)]
    assert len(await client.ensure(pinned, "ltpc", pinned=True)) == MAX_INSTRUMENTS - 2
    await client.ensure([(2, 1), (2, 2)], "oc")
    accepted = await client.ensure([(2, 3)], "oc")
    assert accepted == [(2, 3)]
    assert client.subscription_count() == MAX_INSTRUMENTS
    assert (2, 1) not in client._subs and all(k in client._subs for k in pinned)
    # Everything left is pinned except two: adding three more can only fit two.
    accepted = await client.ensure([(2, 10), (2, 11), (2, 12)], "oc")
    assert len(accepted) == 2


async def test_watchdog_resends_silent_subscription_then_marks_it_silent():
    class Clock:
        now = 0.0
        sleeps = 0

    async def fake_sleep(seconds):
        Clock.now += seconds
        Clock.sleeps += 1
        if Clock.sleeps > 8:
            raise asyncio.CancelledError

    async def get_key():
        return "k"

    client = MarketSocketClient("wss://x", get_key, PriceCache(), sleep=fake_sleep, clock=lambda: Clock.now)
    ws = FakeWS([], drop_after=False)
    client._ws = ws
    await client.ensure([(1, 999999)], "ltp")  # 021 silently ignores unknown tokens
    try:
        await client._watchdog()
    except asyncio.CancelledError:
        pass
    subscribes = [m for m in ws.sent if m["Task"] == "subscribe"]
    assert len(subscribes) == 3  # initial + WATCHDOG_MAX_RETRIES re-sends
    assert (1, 999999) in client.silent


async def test_mode_only_upgrades():
    async def get_key():
        return "k"

    client = MarketSocketClient("wss://x", get_key, PriceCache())
    await client.ensure([(1, 1)], "ltpc", pinned=True)
    await client.ensure([(1, 1)], "ltp")
    assert client._subs[(1, 1)].mode == "ltpc"
    await client.ensure([(1, 1)], "full")
    assert client._subs[(1, 1)].mode == "full"
