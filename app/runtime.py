"""
Kraken runtime: wires the 021 gateway, instrument cache, market socket, candle service and the
copilot into one object owned by the single uvicorn worker.

Background loops (all tolerant of 021 / Redis / Postgres being down):
- instruments: load today's disk cache or download; re-check every 30 min.
- market socket: connect, resubscribe, reconnect forever.
- watchlist: every 60 s read holdings + positions, keep their prices subscribed (pinned), and
  publish the analysis watchlist to Redis for the Celery backfill.
- orders (Level 2, needs the Postgres order tables): boot recovery of unresolved sends, the
  reconciler loop, and the orders socket with REST catch-up.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from app.config.settings import Settings
from domains.broker.domain.errors import BrokerError
from domains.broker.infrastructure.instruments import (
    InstrumentRepository,
    InstrumentStore,
    parse_instruments_csv,
    today_ist,
)
from domains.broker.infrastructure.rest_client import TradeRestClient
from domains.copilot.application.chat_service import ConversationStore, CopilotChatService
from domains.copilot.application.draft_tools import DraftToolbox
from domains.copilot.application.order_builder import OrderBuilder
from domains.copilot.application.read_tools import MarketServices, ReadToolbox
from domains.copilot.infrastructure.gemini_adapter import GeminiLLM
from domains.historical.application.candle_service import CandleService
from domains.marketdata.domain.price_cache import PriceCache
from domains.marketdata.domain.symbol_map import analysis_key, yfinance_ticker
from domains.marketdata.infrastructure.market_socket import MarketSocketClient
from domains.marketdata.infrastructure.orders_socket import OrdersSocketClient
from domains.orders.application.execution import ExecutionService
from domains.orders.application.hub import UserHub
from domains.orders.application.proposals import ProposalService
from domains.orders.application.reconciler import Reconciler
from domains.orders.application.tracker import OrderTracker
from shared.contracts.instruments import EXCHANGE_TO_WS_CODE
from shared.logging.logger import get_correlation_id

logger = logging.getLogger(__name__)

WATCHLIST_INTERVAL_SECONDS = 60
INSTRUMENT_CHECK_SECONDS = 1800


async def _ohlc_repo():
    from domains.historical.infrastructure.persistence.ohlc_repository import TimescaleOhlcRepository
    from shared.infrastructure.database import get_database_pool

    return TimescaleOhlcRepository(await get_database_pool())


class KrakenRuntime:
    def __init__(self, settings: Settings, *, llm=None, transport=None, order_store=None, audit_sink=None):
        self.settings = settings
        self.store = order_store
        self.audit = audit_sink
        self.hub = UserHub()
        self.execution: Optional[ExecutionService] = None
        self.proposals: Optional[ProposalService] = None
        self.reconciler: Optional[Reconciler] = None
        self.tracker: Optional[OrderTracker] = None
        self.orders_socket: Optional[OrdersSocketClient] = None
        self.orders_error: Optional[str] = None
        self.broker = TradeRestClient(
            settings.TradeApiBaseUrl,
            settings.TradeApiUsername,
            settings.TradeApiPassword,
            timeout_seconds=settings.TradeApiTimeoutSeconds,
            rate_per_second=settings.TradeApiRatePerSecond,
            max_get_retries=settings.TradeApiMaxGetRetries,
            transport=transport,
            audit=self._audit_http,
        )
        self.instruments = InstrumentStore()
        self.instrument_repo = InstrumentRepository(settings.InstrumentsCachePath)
        self.cache = PriceCache()
        self.socket = MarketSocketClient(settings.TradeWsBaseUrl, self.broker.get_ephemeral_key, self.cache)
        from domains.historical.infrastructure.yfinance_daily import fetch_daily_candles

        self.candles = CandleService(_ohlc_repo, fetch_daily_candles, days=settings.BackfillDays)
        self.toolbox = ReadToolbox(MarketServices(self.broker, self.instruments, self.socket, self.cache, self.candles))
        self.chat = CopilotChatService(
            llm or GeminiLLM(settings.GeminiApiKey, settings.GeminiModel),
            self.toolbox,
            history=ConversationStore(),
            max_tool_calls=settings.ChatMaxToolCalls,
            max_message_chars=settings.ChatMaxMessageChars,
        )
        self._tasks: list[asyncio.Task] = []
        self._watchlist: dict[str, str] = {}
        self.last_watchlist_sync: Optional[datetime] = None
        self.last_error: Optional[str] = None

    # ── lifecycle ──
    async def start(self) -> None:
        self._load_instruments_from_disk()
        await self.init_orders()
        if not self.broker.configured:
            logger.warning("021 credentials not configured; broker features disabled")
            return
        self._tasks.append(asyncio.create_task(self._instrument_loop(), name="kraken-instruments"))
        self.socket.start()
        self._tasks.append(asyncio.create_task(self._watchlist_loop(), name="kraken-watchlist"))
        if self.execution is not None:
            recovered = await self.reconciler.recover_on_boot()
            if recovered:
                logger.warning("Recovered %d order(s) left mid-send by a restart; reconciling before anything else", recovered)
            self.reconciler.start()
            self.orders_socket.start()

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        if self.reconciler is not None:
            await self.reconciler.stop()
        if self.orders_socket is not None:
            await self.orders_socket.stop()
        await self.socket.stop()
        await self.broker.aclose()

    # ── orders (Level 2) ──
    async def init_orders(self) -> bool:
        """Wire proposals, execution, reconciler and tracking. Needs a durable order store: without
        the Postgres tables, order features stay off rather than fall back to memory (a restart
        would lose unresolved sends)."""
        if self.store is None:
            try:
                from domains.orders.infrastructure.pg_store import PgAuditSink, PgOrderStore
                from shared.infrastructure.database import get_database_pool

                pool = await asyncio.wait_for(get_database_pool(), timeout=8)
                if await pool.fetchval("SELECT to_regclass('kraken_order_journal')") is None:
                    raise RuntimeError("order tables missing; run scripts/migrate.py")
                self.store, self.audit = PgOrderStore(pool), PgAuditSink(pool)
            except Exception as exc:
                self.orders_error = f"order store unavailable: {exc}"[:200]
                logger.error("Order features disabled: %s", self.orders_error)
                return False
        builder = OrderBuilder(self.toolbox)
        self.proposals = ProposalService(self.store, self.audit)
        drafts = DraftToolbox(builder, self.proposals)
        self.reconciler = Reconciler(self.store, self.broker, self.audit, self.hub)
        self.tracker = OrderTracker(self.store, self.broker, self.audit, self.hub, ucc=self.settings.TradeApiUsername)
        self.reconciler.on_not_placed = self.tracker.remember_not_placed
        self.execution = ExecutionService(
            self.store, self.broker, self.audit, self.hub,
            pre_send_check=builder.pre_send_check, requote=drafts.requote, on_unknown=self.reconciler.kick,
        )
        self.orders_socket = OrdersSocketClient(
            self.settings.TradeWsBaseUrl, self.broker.get_ephemeral_key, self.tracker.on_packet, self.tracker.catch_up,
        )
        self.chat.enable_orders(drafts)
        self.orders_error = None
        return True

    async def _audit_http(self, event: dict) -> None:
        # Every order action and every failed 021 call goes to the audit trail (successful reads are noise).
        if self.audit is None or (not event.get("order_action") and event.get("outcome") == "ok" and (event.get("status") or 0) < 400):
            return
        await self.audit.record("broker_http", request_id=get_correlation_id(), data=event)

    # ── instruments ──
    def _load_instruments_from_disk(self) -> None:
        text, loaded_for = self.instrument_repo.load()
        if text:
            self.instruments.load(parse_instruments_csv(text), loaded_for=loaded_for)
            logger.info("Loaded %d instruments from disk cache (for %s)", len(self.instruments), loaded_for)

    async def refresh_instruments(self) -> None:
        raw = await self.broker.download_instruments()
        text = raw.decode("utf-8", errors="replace")
        rows = await asyncio.to_thread(parse_instruments_csv, text)
        if not rows:
            raise BrokerError("021 instruments file parsed to zero rows")
        today = today_ist()
        self.instruments.load(rows, loaded_for=today)
        await asyncio.to_thread(self.instrument_repo.save, raw, today)
        logger.info("Instrument master refreshed: %d rows for %s", len(rows), today)

    async def _instrument_loop(self) -> None:
        while True:
            if not self.instruments.is_fresh():
                try:
                    await self.refresh_instruments()
                except Exception as exc:
                    self.last_error = f"instrument refresh failed: {type(exc).__name__}"
                    logger.warning("%s (%s)", self.last_error, exc)
                    await asyncio.sleep(60)
                    continue
            await asyncio.sleep(INSTRUMENT_CHECK_SECONDS)

    # ── watchlist ──
    async def sync_watchlist(self) -> None:
        positions, holdings = await asyncio.gather(self.broker.get_positions(), self.broker.get_holdings())
        keys: set[tuple[int, int]] = set()
        analysis: dict[str, str] = {}
        for p in positions:
            code = EXCHANGE_TO_WS_CODE.get(str(p.get("exchange")))
            if code is None or not int(p.get("netQuantity", 0) or 0):
                continue
            keys.add((code, int(p.get("token", 0) or 0)))
            inst = self.instruments.get(str(p.get("exchange")), int(p.get("token", 0) or 0))
            if inst is not None and inst.is_derivative:
                inst = self.instruments.get(inst.underlying_exchange, inst.underlying_token) or self.instruments.index(inst.symbol)
            if inst is not None and (ticker := yfinance_ticker(inst)):
                analysis[analysis_key(inst)] = ticker
        for h in holdings:
            inst = self.instruments.equity_by_isin(str(h.get("isin") or "")) or self.instruments.equity(str(h.get("symbol", "")))
            if inst is None:
                continue
            keys.add((inst.ws_code, inst.token))
            if ticker := yfinance_ticker(inst):
                analysis[analysis_key(inst)] = ticker
        await self.socket.ensure(sorted(keys), "ltpc", pinned=True)
        new_symbols = set(analysis) - set(self._watchlist)
        self._watchlist = analysis
        self.last_watchlist_sync = datetime.now(timezone.utc)
        await self._publish_watchlist(analysis, new_symbols)

    async def _publish_watchlist(self, analysis: dict[str, str], new_symbols: set[str]) -> None:
        if not analysis:
            return
        try:
            from domains.historical.tasks import WATCHLIST_KEY
            from shared.infrastructure.redis_client import get_redis_client

            redis = await get_redis_client()
            pipe = redis.pipeline()
            pipe.delete(WATCHLIST_KEY)
            pipe.hset(WATCHLIST_KEY, mapping=analysis)
            await pipe.execute()
            if new_symbols:
                from shared.infrastructure.celery_app import celery_app

                items = sorted((k, analysis[k]) for k in new_symbols)
                # Blocking broker call: keep it off the event loop that serves approvals.
                await asyncio.to_thread(celery_app.send_task, "historical.backfill_daily", kwargs={"items": items})
        except Exception as exc:
            logger.debug("Publishing analysis watchlist failed: %s", exc)

    async def _watchlist_loop(self) -> None:
        while True:
            try:
                await self.sync_watchlist()
            except Exception as exc:
                self.last_error = f"watchlist sync failed: {type(exc).__name__}"
                logger.warning("%s (%s)", self.last_error, exc)
            await asyncio.sleep(WATCHLIST_INTERVAL_SECONDS)

    # ── status ──
    def status(self) -> dict:
        return {
            "broker_configured": self.broker.configured,
            "broker_token_expires_at": self.broker.tokens.expires_at.isoformat() if self.broker.tokens.expires_at else None,
            "instruments_loaded": len(self.instruments),
            "instruments_for": self.instruments.loaded_for.isoformat() if self.instruments.loaded_for else None,
            "instruments_fresh": self.instruments.is_fresh(),
            "market_socket_connected": self.socket.connected,
            "market_feed_healthy": self.cache.feed_healthy(),
            "market_socket_connects": self.socket.connect_count,
            "subscriptions": self.socket.subscription_count(),
            "silent_subscriptions": len(self.socket.silent),
            "watchlist_symbols": len(self._watchlist),
            "last_watchlist_sync": self.last_watchlist_sync.isoformat() if self.last_watchlist_sync else None,
            "llm_configured": bool(self.settings.GeminiApiKey),
            "orders_enabled": self.execution is not None,
            "orders_error": self.orders_error,
            "orders_socket_connected": bool(self.orders_socket and self.orders_socket.connected),
            "trading_kill_switch": self.settings.TradingKillSwitch,
            "last_error": self.last_error or self.socket.last_error,
        }
