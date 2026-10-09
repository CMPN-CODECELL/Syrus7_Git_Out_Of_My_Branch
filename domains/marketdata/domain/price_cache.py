"""
In-memory latest-value cache for 021 market data, keyed by (websocket exchange code, token).

Staleness is decided per connection, not per tick: illiquid instruments may not change for
minutes, so "no new tick" is not "stale". A quote is stale when the socket is down, when the
connection has been silent (not even a heartbeat) for too long, or when the quote predates the
current connection and has not been refreshed by the post-subscribe snapshot.
"""
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Callable, Optional

from domains.marketdata.domain.packets import FullPacket, LtpPacket, OptionChainPacket

SILENCE_STALE_SECONDS = 30.0


@dataclass(frozen=True)
class Quote:
    exchange_code: int
    token: int
    ltp: Optional[int] = None
    open: Optional[int] = None
    high: Optional[int] = None
    low: Optional[int] = None
    prev_close: Optional[int] = None
    volume: Optional[int] = None
    oi: Optional[int] = None
    iv: Optional[float] = None
    best_bid: Optional[int] = None
    best_ask: Optional[int] = None
    greeks: Optional[dict] = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    connection_epoch: int = 0


class PriceCache:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic):
        self._quotes: dict[tuple[int, int], Quote] = {}
        self._clock = clock
        self.connected = False
        self.connection_epoch = 0
        self._last_frame_at: Optional[float] = None

    # ── connection state (driven by the socket client) ──
    def on_connected(self) -> None:
        self.connection_epoch += 1
        self.connected = True
        self._last_frame_at = self._clock()

    def on_disconnected(self) -> None:
        self.connected = False

    def on_frame(self) -> None:
        self._last_frame_at = self._clock()

    def feed_healthy(self) -> bool:
        if not self.connected or self._last_frame_at is None:
            return False
        return (self._clock() - self._last_frame_at) <= SILENCE_STALE_SECONDS

    # ── updates ──
    def apply(self, packet) -> Quote:
        key = (packet.exchange_code, packet.token)
        current = self._quotes.get(key) or Quote(exchange_code=packet.exchange_code, token=packet.token)
        now = datetime.now(timezone.utc)
        if isinstance(packet, LtpPacket):
            updated = replace(current, ltp=packet.ltp,
                              open=packet.open if packet.open is not None else current.open,
                              prev_close=packet.prev_close if packet.prev_close is not None else current.prev_close)
        elif isinstance(packet, FullPacket):
            updated = replace(current, ltp=packet.ltp, open=packet.open, high=packet.high, low=packet.low,
                              prev_close=packet.close, volume=packet.volume,
                              oi=packet.oi if packet.oi is not None else current.oi,
                              best_bid=packet.best_bid, best_ask=packet.best_ask)
        elif isinstance(packet, OptionChainPacket):
            updated = replace(
                current,
                ltp=packet.ltp if packet.ltp is not None else current.ltp,
                oi=packet.oi if packet.oi is not None else current.oi,
                volume=packet.volume if packet.volume is not None else current.volume,
                iv=packet.iv if packet.iv is not None else current.iv,
                best_bid=packet.best_bid if packet.best_bid is not None else current.best_bid,
                best_ask=packet.best_ask if packet.best_ask is not None else current.best_ask,
                greeks=packet.greeks if packet.greeks is not None else current.greeks,
            )
        else:
            return current
        updated = replace(updated, updated_at=now, connection_epoch=self.connection_epoch)
        self._quotes[key] = updated
        return updated

    # ── reads ──
    def get(self, exchange_code: int, token: int) -> Optional[Quote]:
        return self._quotes.get((exchange_code, token))

    def is_stale(self, quote: Optional[Quote]) -> bool:
        if quote is None or quote.ltp is None:
            return True
        if not self.feed_healthy():
            return True
        return quote.connection_epoch != self.connection_epoch

    def fresh_since(self, exchange_code: int, token: int, since: datetime) -> bool:
        quote = self.get(exchange_code, token)
        return quote is not None and quote.updated_at >= since and quote.connection_epoch == self.connection_epoch
