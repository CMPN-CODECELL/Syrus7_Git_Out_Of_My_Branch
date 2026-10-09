"""
021 orders websocket client: binary order events (TC 4 NSE, TC 8 BSE), one packet per frame.

Events while disconnected are not replayed by 021, so every (re)connect is followed by a REST
catch-up (on_connected callback). Reconnects with exponential backoff + jitter and a fresh key.
"""
import asyncio
import logging
import random
import time
from typing import Any, Awaitable, Callable, Optional

from domains.marketdata.domain.packets import OrderUpdatePacket, parse_order_frame

logger = logging.getLogger(__name__)

PacketHandler = Callable[[OrderUpdatePacket], Awaitable[None]]


async def _default_connect(url: str):
    import websockets
    return await websockets.connect(url, max_size=2**20, open_timeout=10, close_timeout=5)


class OrdersSocketClient:
    def __init__(
        self,
        ws_base_url: str,
        get_key: Callable[[], Awaitable[str]],
        on_packet: PacketHandler,
        on_connected: Callable[[], Awaitable[Any]],
        *,
        connect=_default_connect,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
        rng: Callable[[], float] = random.random,
    ):
        self._url = ws_base_url.rstrip("/") + "/orders"
        self._get_key = get_key
        self._on_packet = on_packet
        self._on_connected = on_connected
        self._connect = connect
        self._sleep = sleep
        self._clock = clock
        self._rng = rng
        self._ws: Any = None
        self._task: Optional[asyncio.Task] = None
        self._stopping = False
        self.connected = False
        self.connect_count = 0
        self.last_error: Optional[str] = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stopping = False
            self._task = asyncio.create_task(self._run(), name="kraken-orders-socket")

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

    async def _run(self) -> None:
        backoff = 1.0
        while not self._stopping:
            started = self._clock()
            try:
                key = await self._get_key()
                self._ws = await self._connect(f"{self._url}?token={key}")
                self.connected = True
                self.connect_count += 1
                self.last_error = None
                logger.info("Orders socket connected (#%d); catching up via REST", self.connect_count)
                try:
                    await self._on_connected()
                except Exception as exc:
                    logger.warning("order catch-up failed: %s", exc)
                async for message in self._ws:
                    if isinstance(message, str):
                        continue
                    packet = parse_order_frame(message)
                    if packet is None:
                        logger.warning("Unrecognised orders-socket frame (%d bytes)", len(message))
                        continue
                    try:
                        await self._on_packet(packet)
                    except Exception as exc:
                        logger.warning("order event handling failed: %s", exc)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"[:200]
                logger.warning("Orders socket error: %s", self.last_error)
            finally:
                self.connected = False
                ws, self._ws = self._ws, None
                if ws is not None:
                    try:
                        await ws.close()
                    except Exception:
                        pass
            if self._stopping:
                break
            if self._clock() - started > 60:
                backoff = 1.0
            await self._sleep(backoff * (0.5 + self._rng()))
            backoff = min(backoff * 2, 30.0)
