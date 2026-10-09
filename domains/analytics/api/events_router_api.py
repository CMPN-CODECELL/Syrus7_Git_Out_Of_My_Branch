"""
File Overview: Real-time WebSocket aggregator for pushing market data to clients via shared Redis Pub/Sub subscription.

All Functions/Classes:
- ConnectionManager: Orchestrates active WebSocket connections and task lifecycle. Take data from Redis Pub/Sub and send to WebSocket clients.
- connect: Register new WebSocket for a symbol. Take symbol/WS and send accepted connection status.
- disconnect: Clean up connections and stop idle background tasks. Take symbol/WS and send termination signals.
- mark_client_alive: Update last activity timestamp for a client. Take symbol/WS and send updated timestamp to ConnectionManager.
- broadcast: Queue JSON messages to all connected clients for a symbol. Take symbol/message and send to client queues.
- _ensure_background_tasks_locked: Lazily start global Redis listener and cleanup loop. Take lock control and send task initialization.
- _stop_background_tasks_if_idle_locked: Terminate background workers if no clients remain. Take lock control and send cancellation signals.
- _sender_loop: Per-client worker for popping messages and sending JSON. Take data from Queue and send to WebSocket.
- _cleanup_loop: Background task to disconnect idle clients. Take connection map and send disconnect commands.
- WebSocketEndpoint: FastAPI WebSocket entry point. Take symbol from path and send stream of real-time data.
- _derive_type_and_symbol: Parse Redis channel patterns. Take channel string and send (msg_type, symbol) tuple.
- _redis_global_listener: Shared listener for all symbol patterns. Take data from Redis Pub/Sub and send to ConnectionManager.broadcast.

Endpoints/APIs:
- WS /ws/{symbol}.

Database Tables:
- Redis (Pub/Sub).
"""

import json
import asyncio
import logging
from dataclasses import dataclass

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import get_settings
from shared.constants import Channels

logger = logging.getLogger(__name__)

router = APIRouter()

_CLIENT_QUEUE_MAX_SIZE = 200
_CLIENT_SEND_TIMEOUT_SECONDS = 5.0
_CLIENT_MAX_DROPPED_MESSAGES = 25
_CLIENT_STALE_SECONDS = 120.0
_CLEANUP_INTERVAL_SECONDS = 15.0


@dataclass
class _ClientConnection:
    websocket: WebSocket
    queue: asyncio.Queue[dict]
    sender_task: asyncio.Task
    dropped_messages: int = 0
    last_activity_ts: float = 0.0


class ConnectionManager:
    """Tracks active WS clients and a shared Redis subscription fan-out."""

    def __init__(self):
        self._Connections: dict[str, dict[WebSocket, _ClientConnection]] = {}
        self._GlobalSubscriberTask: asyncio.Task | None = None
        self._GlobalSubscriberStopEvent: asyncio.Event | None = None
        self._CleanupTask: asyncio.Task | None = None
        self._CleanupStopEvent: asyncio.Event | None = None
        self._PollingTask: asyncio.Task | None = None
        self._PollingStopEvent: asyncio.Event | None = None
        self._Lock = asyncio.Lock()

    async def connect(self, symbol: str, ws: WebSocket) -> None:
        await ws.accept()
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=_CLIENT_QUEUE_MAX_SIZE)
        sender_task = asyncio.create_task(self._sender_loop(symbol, ws, queue))
        now = asyncio.get_running_loop().time()

        async with self._Lock:
            if symbol not in self._Connections:
                self._Connections[symbol] = {}
            self._Connections[symbol][ws] = _ClientConnection(
                websocket=ws,
                queue=queue,
                sender_task=sender_task,
                last_activity_ts=now,
            )
            total = len(self._Connections[symbol])
            await self._ensure_background_tasks_locked()

        logger.info("WS connected: %s (total: %d)", symbol, total)

    async def disconnect(self, symbol: str, ws: WebSocket, close_ws: bool = True) -> None:
        connection: _ClientConnection | None = None

        async with self._Lock:
            by_symbol = self._Connections.get(symbol)
            if by_symbol and ws in by_symbol:
                connection = by_symbol.pop(ws)
                if not by_symbol:
                    del self._Connections[symbol]
                await self._stop_background_tasks_if_idle_locked()

        if close_ws:
            try:
                await ws.close()
            except Exception:
                pass

        if connection is not None:
            current = asyncio.current_task()
            if connection.sender_task is not current and not connection.sender_task.done():
                connection.sender_task.cancel()
                await asyncio.gather(connection.sender_task, return_exceptions=True)

        logger.info("WS disconnected: %s", symbol)

    async def mark_client_alive(self, symbol: str, ws: WebSocket) -> None:
        now = asyncio.get_running_loop().time()
        async with self._Lock:
            conn = self._Connections.get(symbol, {}).get(ws)
            if conn is not None:
                conn.last_activity_ts = now

    async def broadcast(self, symbol: str, message: dict) -> None:
        """
        Queue a JSON message to all connected clients for a symbol.

        Messages are queued with bounded backpressure controls to prevent
        slow consumers from affecting fast consumers.
        """
        stale: list[WebSocket] = []

        async with self._Lock:
            connections = list(self._Connections.get(symbol, {}).values())
            now = asyncio.get_running_loop().time()
            for conn in connections:
                try:
                    conn.queue.put_nowait(message)
                    conn.last_activity_ts = now
                    continue
                except asyncio.QueueFull:
                    pass

                # Queue is full: drop oldest, keep newest.
                try:
                    conn.queue.get_nowait()
                    conn.queue.put_nowait(message)
                    conn.dropped_messages += 1
                    conn.last_activity_ts = now
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    conn.dropped_messages += 1

                if conn.dropped_messages >= _CLIENT_MAX_DROPPED_MESSAGES:
                    stale.append(conn.websocket)

        for ws in stale:
            logger.warning("Disconnecting slow WS client for symbol=%s", symbol)
            await self.disconnect(symbol, ws)

    async def _ensure_background_tasks_locked(self) -> None:
        if self._GlobalSubscriberTask is None or self._GlobalSubscriberTask.done():
            self._GlobalSubscriberStopEvent = asyncio.Event()
            self._GlobalSubscriberTask = asyncio.create_task(
                _redis_global_listener(self._GlobalSubscriberStopEvent)
            )
            logger.info("WS global Redis subscriber started")

        if self._CleanupTask is None or self._CleanupTask.done():
            self._CleanupStopEvent = asyncio.Event()
            self._CleanupTask = asyncio.create_task(self._cleanup_loop(self._CleanupStopEvent))
            logger.info("WS stale-client cleanup loop started")

        if self._PollingTask is None or self._PollingTask.done():
            self._PollingStopEvent = asyncio.Event()
            self._PollingTask = asyncio.create_task(self._polling_loop(self._PollingStopEvent))
            logger.info("WS dynamic polling loop started")

    async def _stop_background_tasks_if_idle_locked(self) -> None:
        if self._Connections:
            return

        subscriber_task = self._GlobalSubscriberTask
        subscriber_stop = self._GlobalSubscriberStopEvent
        cleanup_task = self._CleanupTask
        cleanup_stop = self._CleanupStopEvent
        polling_task = self._PollingTask
        polling_stop = self._PollingStopEvent

        self._GlobalSubscriberTask = None
        self._GlobalSubscriberStopEvent = None
        self._CleanupTask = None
        self._CleanupStopEvent = None
        self._PollingTask = None
        self._PollingStopEvent = None

        if subscriber_stop is not None:
            subscriber_stop.set()
        if cleanup_stop is not None:
            cleanup_stop.set()
        if polling_stop is not None:
            polling_stop.set()

        current = asyncio.current_task()
        tasks = [t for t in (subscriber_task, cleanup_task, polling_task) if t is not None and t is not current]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
            logger.info("WS background tasks stopped (no active clients)")

    async def _sender_loop(
        self,
        symbol: str,
        ws: WebSocket,
        queue: asyncio.Queue[dict],
    ) -> None:
        try:
            while True:
                message = await queue.get()
                await asyncio.wait_for(
                    ws.send_json(message),
                    timeout=_CLIENT_SEND_TIMEOUT_SECONDS,
                )
                await self.mark_client_alive(symbol, ws)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug("WS sender loop ended for %s: %s", symbol, exc)
        finally:
            # Ensure this websocket is fully cleaned up if sender loop exits.
            await self.disconnect(symbol, ws, close_ws=False)

    async def _cleanup_loop(self, stop_event: asyncio.Event) -> None:
        try:
            loop = asyncio.get_running_loop()
            while not stop_event.is_set():
                await asyncio.sleep(_CLEANUP_INTERVAL_SECONDS)
                now = loop.time()
                stale_clients: list[tuple[str, WebSocket]] = []

                async with self._Lock:
                    for symbol, by_socket in self._Connections.items():
                        for ws, conn in by_socket.items():
                            idle_seconds = now - conn.last_activity_ts
                            if idle_seconds >= _CLIENT_STALE_SECONDS:
                                stale_clients.append((symbol, ws))

                for symbol, ws in stale_clients:
                    logger.info("Disconnecting stale WS client for %s", symbol)
                    await self.disconnect(symbol, ws)
        except asyncio.CancelledError:
            pass

    async def _polling_loop(self, stop_event: asyncio.Event) -> None:
        try:
            last_price_poll: dict[str, float] = {}
            last_options_poll: dict[str, float] = {}

            # Dynamic imports to prevent circular references
            from domains.ingestion.tasks.ingestion_tasks import poll_prices
            from domains.ingestion.tasks.market_tasks import fetch_and_publish_options

            loop = asyncio.get_running_loop()

            while not stop_event.is_set():
                now = loop.time()
                active_symbols = []
                async with self._Lock:
                    active_symbols = list(self._Connections.keys())

                settings = get_settings()
                price_interval = float(settings.PricePollIntervalSeconds)
                options_interval = float(settings.OptionsPollIntervalSeconds)

                for symbol in active_symbols:
                    # 1. Price Polling
                    last_price = last_price_poll.get(symbol, 0.0)
                    if now - last_price >= price_interval:
                        try:
                            poll_prices.delay(symbol)
                            logger.info("Dispatched live price poll task for %s", symbol)
                        except Exception as exc:
                            logger.error("Failed to dispatch price poll for %s: %s", symbol, exc)
                        last_price_poll[symbol] = now

                    # 2. Options Polling (single consolidated task)
                    last_opts = last_options_poll.get(symbol, 0.0)
                    if now - last_opts >= options_interval:
                        try:
                            fetch_and_publish_options.delay(symbol)
                            logger.info("Dispatched live options poll task for %s", symbol)
                        except Exception as exc:
                            logger.error("Failed to dispatch options poll for %s: %s", symbol, exc)
                        last_options_poll[symbol] = now

                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("Dynamic polling loop error: %s", exc, exc_info=True)


_MAX_CLIENTS_PER_SYMBOL = 100
_Manager = ConnectionManager()


@router.websocket("/ws/{symbol}")
async def websocket_endpoint(
    websocket: WebSocket,
    symbol: str,
    token: str | None = None
):
    """
    Real-time WebSocket endpoint for a symbol.

    Subscribes to Redis Pub/Sub channels and pushes events:
        - {"type": "price", "data": {...}}
        - {"type": "options", "data": {...}}
        - {"type": "trigger", "data": {...}}
        - {"type": "alert", "data": {...}}
    """
    symbol_upper = symbol.upper()

    # Validate symbol format and existence
    from shared.utils.symbol_validator import SymbolValidator
    if not SymbolValidator.validate(symbol_upper):
        await websocket.close(code=4001, reason=f"Symbol {symbol_upper} is invalid or not supported")
        return

    symbol_clean = SymbolValidator.get_clean_symbol(symbol_upper)

    # Check connection limits per symbol to prevent socket exhaustion
    current_symbol_clients = len(_Manager._Connections.get(symbol_clean, {}))
    if current_symbol_clients >= _MAX_CLIENTS_PER_SYMBOL:
        await websocket.close(code=4029, reason="Too many concurrent connections for this symbol")
        return

    await _Manager.connect(symbol_clean, websocket)

    try:
        # Keep connection alive — listen for client messages (ping/pong)
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=60.0)
            except asyncio.TimeoutError:
                # Send server-side ping heartbeat or disconnect if dead
                await websocket.send_json({"type": "ping"})
                continue

            await _Manager.mark_client_alive(symbol_clean, websocket)
            # Client can send {"action": "ping"} to keep alive
            if data:
                try:
                    msg = json.loads(data)
                    if msg.get("action") == "ping":
                        await websocket.send_json({"type": "pong"})
                except json.JSONDecodeError:
                    pass

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected: %s", symbol_clean)
    except Exception as exc:
        logger.error("WebSocket error for %s: %s", symbol_clean, exc)
    finally:
        await _Manager.disconnect(symbol_clean, websocket)


def _derive_type_and_symbol(channel: str) -> tuple[str, str]:
    """Map Redis channel name to event type and symbol."""
    prefixes = {
        "market.price_updated.": "price",
        "market.options_updated.": "options",
        "market.price_trigger.": "trigger",
        "alerts.dispatched.": "alert",
    }
    for prefix, msg_type in prefixes.items():
        if channel.startswith(prefix):
            symbol = channel[len(prefix):].upper()
            return msg_type, symbol
    return "unknown", ""


async def _redis_global_listener(stop_event: asyncio.Event):
    """Subscribe once globally and fan out messages by symbol."""
    pubsub = None
    try:
        from shared.infrastructure.redis_client import get_redis_client
        redis = await get_redis_client()

        # Create one shared pub/sub connection for all WS clients.
        pubsub = redis.pubsub()

        patterns = [
            Channels.PRICE_UPDATED.format(symbol="*"),
            Channels.OPTIONS_UPDATED.format(symbol="*"),
            Channels.PRICE_TRIGGER.format(symbol="*"),
            Channels.ALERT_DISPATCHED.format(symbol="*"),
        ]

        await pubsub.psubscribe(*patterns)

        logger.info(
            "WS global Redis listener started on %d channel patterns",
            len(patterns),
        )

        while not stop_event.is_set():
            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=0.1,
            )
            if message is None:
                continue

            channel = message["channel"]
            if isinstance(channel, bytes):
                channel = channel.decode("utf-8")
            if not isinstance(channel, str):
                continue

            data_str = message["data"]
            if isinstance(data_str, bytes):
                data_str = data_str.decode("utf-8")

            msg_type, symbol = _derive_type_and_symbol(channel)
            if not symbol:
                continue

            try:
                payload = json.loads(data_str)
                await _Manager.broadcast(symbol, {"type": msg_type, "data": payload})
            except (json.JSONDecodeError, Exception) as exc:
                logger.debug("WS forward error: %s", exc)

    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.error("Global Redis listener error: %s", exc)
    finally:
        if pubsub is not None:
            try:
                await pubsub.punsubscribe()
                await pubsub.aclose()
            except Exception:
                pass
