"""A complete Level 2 test world: fake 021, instruments, prices, builder, proposals, execution,
reconciler and tracker, all in memory."""
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional

from app.config.settings import get_settings
from domains.broker.infrastructure.instruments import InstrumentStore, parse_instruments_csv, today_ist
from domains.broker.infrastructure.rest_client import TradeRestClient
from domains.copilot.application.draft_tools import DraftToolbox
from domains.copilot.application.order_builder import OrderBuilder
from domains.copilot.application.read_tools import MarketServices, ReadToolbox
from domains.historical.application.candle_service import CandleService
from domains.marketdata.domain.packets import LtpPacket
from domains.marketdata.domain.price_cache import PriceCache
from domains.orders.application.execution import ExecutionService
from domains.orders.application.hub import UserHub
from domains.orders.application.proposals import ProposalService
from domains.orders.application.reconciler import Reconciler
from domains.orders.application.tracker import OrderTracker
from domains.orders.infrastructure.memory_store import MemoryAuditSink, MemoryOrderStore
from tests.fakes.fake_021 import BASE_URL, Fake021
from tests.fakes.market import FakeSocket, instruments_csv

USER = "user-1"

# (ws code, token): LTP in paise
PRICES = {
    (1, 2885): 280000,   # RELIANCE 2,800.00 (tick 10 paise; circuits 2,500-3,000)
    (1, 11536): 372000,  # TCS
    (1, 1594): 153000,   # INFY
    (1, 1333): 165000,   # HDFCBANK
    (3, 26000): 2452300,  # NIFTY index
}


async def _no_sleep(_):
    return None


@dataclass
class OrdersWorld:
    fake: Fake021
    client: TradeRestClient
    store: MemoryOrderStore
    audit: MemoryAuditSink
    hub: UserHub
    cache: PriceCache
    instruments: InstrumentStore
    toolbox: ReadToolbox
    builder: OrderBuilder
    proposals: ProposalService
    drafts: DraftToolbox
    execution: ExecutionService
    reconciler: Reconciler
    tracker: OrderTracker
    settings_overrides: dict
    market_open: list

    def set_price(self, key: tuple[int, int], ltp: int) -> None:
        self.cache.apply(LtpPacket(key[0], key[1], ltp))

    def settings(self):
        return get_settings().model_copy(update=self.settings_overrides)

    async def propose(self, draft, user_id: str = USER):
        built = await self.builder.build_place(draft)
        return await self.proposals.create(user_id, built)


def build_world(*, market_open: bool = True, seed: int = 7, expiry_day: Optional[date] = None, overrides: Optional[dict] = None) -> OrdersWorld:
    fake = Fake021(seed=seed)
    client = TradeRestClient(BASE_URL, fake.ucc, fake.password, rate_per_second=10_000, max_get_retries=6,
                             transport=fake.transport(), sleep=_no_sleep, rng=lambda: 0.0)
    instruments = InstrumentStore(parse_instruments_csv(instruments_csv(expiry_day)), loaded_for=today_ist())
    cache = PriceCache()
    cache.on_connected()
    for (code, token), ltp in PRICES.items():
        cache.apply(LtpPacket(code, token, ltp, prev_close=ltp))

    async def no_repo():
        return None

    toolbox = ReadToolbox(MarketServices(client, instruments, FakeSocket(cache), cache, CandleService(no_repo, None)))
    store, audit, hub = MemoryOrderStore(), MemoryAuditSink(), UserHub()
    holder: dict = {"overrides": dict(overrides or {}), "open": [market_open]}

    def settings():
        return get_settings().model_copy(update=holder["overrides"])

    builder = OrderBuilder(toolbox, settings=settings, market_open=lambda _now: holder["open"][0])
    proposals = ProposalService(store, audit)
    drafts = DraftToolbox(builder, proposals)
    reconciler = Reconciler(store, client, audit, hub)
    tracker = OrderTracker(store, client, audit, hub, ucc=fake.ucc)
    reconciler.on_not_placed = tracker.remember_not_placed
    execution = ExecutionService(store, client, audit, hub, pre_send_check=builder.pre_send_check,
                                 requote=drafts.requote, on_unknown=reconciler.kick, settings=settings)
    return OrdersWorld(fake, client, store, audit, hub, cache, instruments, toolbox, builder, proposals, drafts,
                       execution, reconciler, tracker, holder["overrides"], holder["open"])


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
