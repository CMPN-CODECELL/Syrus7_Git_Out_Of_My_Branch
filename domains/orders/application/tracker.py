"""
Order tracker: keeps journal rows in step with 021's order status.

Socket events are hints; REST is the source of truth. On each event for a known order, the
tracker reads GET /orders/{id} (and its trades for fills) and stores that. After every
(re)connect it catches up with GET /orders, because the orders socket does not replay.
An event for an order the journal doesn't know may be a late appearance of a send that the
reconciler marked NOT_PLACED/UNKNOWN; it is linked if it matches exactly one such row.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from domains.broker.domain.errors import BrokerError
from domains.marketdata.domain.packets import ORDER_STATUS_EVENTS, OrderUpdatePacket
from domains.orders.application.hub import UserHub
from domains.orders.application.reconciler import CLOCK_SKEW, matches_payload
from domains.orders.ports import AuditSink, OrderStore
from shared.contracts.orders import FINAL_ORDER_STATUSES, JournalEntry

logger = logging.getLogger(__name__)

LATE_LINK_WINDOW = timedelta(minutes=15)


class OrderTracker:
    def __init__(self, store: OrderStore, broker, audit: AuditSink, hub: UserHub, *, ucc: str = "",
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.store = store
        self.broker = broker
        self.audit = audit
        self.hub = hub
        self.ucc = ucc.strip().upper()
        self._now = now
        self._late_candidates: list[JournalEntry] = []

    async def _fills(self, order_id: str) -> tuple[int, Optional[int]]:
        try:
            trades = await self.broker.get_order_trades(order_id)
        except BrokerError:
            return 0, None
        qty = sum(abs(int(t.get("quantity", 0) or 0)) for t in trades)
        value = sum(abs(int(t.get("quantity", 0) or 0)) * int(t.get("price", 0) or 0) for t in trades)
        return qty, (round(value / qty) if qty else None)

    async def _apply(self, entry: JournalEntry, order: dict, *, source: str) -> JournalEntry:
        status = str(order.get("status") or entry.order_status or "")
        update: dict = {"order_status": status}
        traded = abs(int(order.get("qtyTraded", 0) or 0))
        if traded and entry.action == "PLACE":
            qty, avg = await self._fills(str(order.get("orderId")))
            update["filled_qty"] = qty or traded
            update["avg_fill_price"] = avg
        reason = str(order.get("reason") or "").strip()
        if reason:
            update["reason"] = "".join(ch for ch in reason if ch.isprintable())[:300]
        if order.get("placedBy") == "RMS":
            update["reason"] = "Squared off automatically by the broker's risk system (RMS), not by Kraken."
        new = entry.model_copy(update=update)
        if new.model_dump(exclude={"updated_at"}) != entry.model_dump(exclude={"updated_at"}):
            await self.store.update_journal(new)
            await self.audit.record("order_status", user_id=new.user_id, proposal_id=new.proposal_id, journal_id=new.id,
                                    order_id=new.order_id, data={"status": status, "source": source, "filled": new.filled_qty})
            new = (await self.store.get_journal(new.id)) or new
            await self.hub.publish_journal(new)
        return new

    async def on_packet(self, packet: OrderUpdatePacket) -> None:
        if self.ucc and packet.ucc and packet.ucc.upper() != self.ucc:
            return  # not our account
        event = ORDER_STATUS_EVENTS.get(packet.status_code, "UNKNOWN")
        await self.audit.record("order_socket_event", order_id=packet.order_id,
                                data={"event": event, "qty": packet.qty, "price": packet.price, "reason": packet.reason})
        entries = await self.store.journal_by_order_id(packet.order_id)
        try:
            order = await self.broker.get_order(packet.order_id)
        except BrokerError as exc:
            logger.info("could not refresh order %s after socket event (%s)", packet.order_id, type(exc).__name__)
            order = None
        if order is None:
            return
        if not entries:
            await self._late_link(order)
            return
        for entry in entries:
            if entry.action == "PLACE" or entry.state == "ACKED":
                await self._apply(entry, order, source="socket")

    async def _late_link(self, order: dict) -> None:
        now = self._now()
        rows = [e for e in await self.store.unresolved_journal() if e.action == "PLACE"]
        rows += [e for e in self._late_candidates if now - e.sent_at <= LATE_LINK_WINDOW]
        placed_at = int(order.get("time", 0) or 0)
        matches = [e for e in rows if matches_payload(order, e.payload) and placed_at >= int((e.sent_at - CLOCK_SKEW).timestamp())]
        if len(matches) != 1:
            return
        entry = matches[0]
        order_id = str(order.get("orderId"))
        if not await self.store.link_order(entry.id, order_id):
            return
        was = entry.state
        entry = entry.model_copy(update={"state": "ACKED", "order_id": order_id, "next_reconcile_at": None,
                                         "reason": f"021 order appeared after being marked {was}" if was == "NOT_PLACED" else entry.reason})
        await self.store.update_journal(entry)
        await self.audit.record("order_late_link", user_id=entry.user_id, proposal_id=entry.proposal_id, journal_id=entry.id,
                                order_id=order_id, data={"previous_state": was})
        await self._apply(entry, order, source="late_link")

    def remember_not_placed(self, entry: JournalEntry) -> None:
        if entry.state == "NOT_PLACED" and entry.action == "PLACE":
            self._late_candidates = [e for e in self._late_candidates if self._now() - e.sent_at <= LATE_LINK_WINDOW] + [entry]

    async def catch_up(self) -> int:
        """REST catch-up after a socket (re)connect: refresh every non-final linked order."""
        open_rows = await self.store.open_journal()
        if not open_rows:
            return 0
        try:
            orders = {str(o.get("orderId")): o for o in await self.broker.get_orders()}
        except BrokerError as exc:
            logger.info("order catch-up failed (%s)", type(exc).__name__)
            return 0
        updated = 0
        for entry in open_rows:
            order = orders.get(entry.order_id or "")
            if order is not None and (order.get("status") != entry.order_status or order.get("qtyTraded")):
                await self._apply(entry, order, source="rest_catch_up")
                updated += 1
        return updated

    @staticmethod
    def is_final(entry: JournalEntry) -> bool:
        return entry.order_status in FINAL_ORDER_STATUSES
