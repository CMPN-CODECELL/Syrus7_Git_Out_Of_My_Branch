"""
Reconciler: resolves journal rows whose outcome is unknown (timeout, gateway error, crash
between claim and send). It only READS 021 (GET /orders); it never sends anything.

PLACE rows are matched to 021 orders on token, exchange, product, |qty|, price (and trigger for
SL), placed no earlier than sent_at - 30 s, among orderIds not already linked to another PLACE
row. Exactly one match -> ACKED; none after the last attempt -> NOT_PLACED; several -> AMBIGUOUS.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from domains.broker.domain.errors import BrokerError
from domains.orders.application.hub import UserHub
from domains.orders.ports import AuditSink, OrderStore
from shared.contracts.instruments import EXCHANGE_TO_REQUEST
from shared.contracts.orders import JournalEntry, OrderPayload

logger = logging.getLogger(__name__)

# Attempt n happens at sent_at + SCHEDULE[n]; after the last one an unmatched PLACE is NOT_PLACED.
SCHEDULE_SECONDS = (2, 5, 10, 20)
CLOCK_SKEW = timedelta(seconds=30)


def order_total_qty(order: dict) -> int:
    return abs(int(order.get("qtyRemaining", 0) or 0)) + abs(int(order.get("qtyTraded", 0) or 0))


def matches_payload(order: dict, payload: OrderPayload) -> bool:
    try:
        if int(order.get("token", 0)) != payload.token:
            return False
        if EXCHANGE_TO_REQUEST.get(str(order.get("exchange")), str(order.get("exchange"))) != payload.exchange:
            return False
        if str(order.get("product")) != payload.product:
            return False
        if order_total_qty(order) != abs(payload.qty):
            return False
        remaining = int(order.get("qtyRemaining", 0) or 0)
        if remaining and (remaining > 0) != (payload.qty > 0):
            return False
        if int(order.get("price", 0) or 0) != payload.price:
            return False
        if order.get("book") and order.get("book") != payload.book:
            return False
        if payload.book == "SL" and int(order.get("triggerPrice", 0) or 0) != (payload.trigger or 0):
            return False
    except (TypeError, ValueError):
        return False
    return True


class Reconciler:
    def __init__(self, store: OrderStore, broker, audit: AuditSink, hub: UserHub, *,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.store = store
        self.broker = broker
        self.audit = audit
        self.hub = hub
        self._now = now
        self._wake = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        # Called with rows marked NOT_PLACED so the tracker can still link a late-appearing 021 order.
        self.on_not_placed: Optional[Callable[[JournalEntry], None]] = None

    def kick(self, _entry: Optional[JournalEntry] = None) -> None:
        self._wake.set()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="kraken-reconciler")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    async def recover_on_boot(self) -> int:
        """Rows left in SENDING by a crash are treated as UNKNOWN and reconciled before anything else."""
        count = 0
        for entry in await self.store.unresolved_journal():
            if entry.state == "SENDING":
                entry = entry.model_copy(update={"state": "UNKNOWN", "reason": "server restarted while sending",
                                                 "next_reconcile_at": self._now()})
                await self.store.update_journal(entry)
                await self.audit.record("reconcile_boot", user_id=entry.user_id, proposal_id=entry.proposal_id, journal_id=entry.id)
                count += 1
        return count

    async def _loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception as exc:
                logger.warning("reconciler pass failed: %s", exc)
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass

    async def run_once(self, *, force: bool = False) -> list[JournalEntry]:
        now = self._now()
        due = [e for e in await self.store.unresolved_journal()
               if force or e.next_reconcile_at is None or e.next_reconcile_at <= now]
        if not due:
            return []
        try:
            orders = await self.broker.get_orders()
        except BrokerError as exc:
            logger.info("reconciler could not read orders (%s); will retry", type(exc).__name__)
            return []
        changed = []
        for entry in due:
            updated = await self._reconcile(entry, orders, now)
            if updated is not None:
                changed.append(updated)
        return changed

    def _schedule(self, entry: JournalEntry, now: datetime) -> JournalEntry:
        attempts = entry.reconcile_attempts + 1
        if attempts >= len(SCHEDULE_SECONDS):
            return entry.model_copy(update={"reconcile_attempts": attempts, "next_reconcile_at": None})
        return entry.model_copy(update={"reconcile_attempts": attempts,
                                        "next_reconcile_at": entry.sent_at + timedelta(seconds=SCHEDULE_SECONDS[attempts])})

    async def _finish(self, entry: JournalEntry, kind: str) -> JournalEntry:
        await self.store.update_journal(entry)
        await self.audit.record(kind, user_id=entry.user_id, proposal_id=entry.proposal_id, journal_id=entry.id,
                                order_id=entry.order_id, data={"state": entry.state, "reason": entry.reason})
        await self.hub.publish_journal(entry)
        if entry.state == "NOT_PLACED" and self.on_not_placed:
            self.on_not_placed(entry)
        return entry

    async def _reconcile(self, entry: JournalEntry, orders: list[dict], now: datetime) -> Optional[JournalEntry]:
        exhausted = entry.reconcile_attempts + 1 >= len(SCHEDULE_SECONDS)
        if entry.action == "PLACE":
            linked = await self.store.linked_place_order_ids()
            earliest = int((entry.sent_at - CLOCK_SKEW).timestamp())
            candidates = [o for o in orders
                          if str(o.get("orderId")) not in linked and matches_payload(o, entry.payload)
                          and int(o.get("time", 0) or 0) >= earliest]
            if len(candidates) == 1:
                order = candidates[0]
                order_id = str(order.get("orderId"))
                if await self.store.link_order(entry.id, order_id):
                    entry = entry.model_copy(update={"state": "ACKED", "order_id": order_id, "order_status": order.get("status"),
                                                     "reason": "confirmed from the 021 order book", "next_reconcile_at": None})
                    return await self._finish(entry, "reconcile_found")
            if len(candidates) > 1:
                ids = ", ".join(str(o.get("orderId")) for o in candidates)
                entry = entry.model_copy(update={"state": "AMBIGUOUS", "next_reconcile_at": None,
                                                 "reason": f"several 021 orders match ({ids}); check them before placing anything else"})
                return await self._finish(entry, "reconcile_ambiguous")
            if exhausted:
                entry = entry.model_copy(update={"state": "NOT_PLACED", "next_reconcile_at": None,
                                                 "reason": "021 has no matching order; it was not placed"})
                return await self._finish(entry, "reconcile_not_placed")
        else:
            order = next((o for o in orders if str(o.get("orderId")) == entry.target_order_id), None)
            if order is not None:
                status = str(order.get("status"))
                if entry.action == "CANCEL" and status in ("Cancelled", "SentForCancellation"):
                    entry = entry.model_copy(update={"state": "ACKED", "order_status": status, "next_reconcile_at": None})
                    return await self._finish(entry, "reconcile_found")
                if entry.action == "MODIFY" and matches_payload(order, entry.payload) and order_total_qty(order) == abs(entry.payload.qty):
                    entry = entry.model_copy(update={"state": "ACKED", "order_status": status, "next_reconcile_at": None})
                    return await self._finish(entry, "reconcile_found")
                if status in ("Executed", "Rejected", "Cancelled"):
                    reason = "filled before the cancel arrived" if entry.action == "CANCEL" and status == "Executed" else f"order is {status}"
                    entry = entry.model_copy(update={"state": "NOT_PLACED", "order_status": status, "reason": reason,
                                                     "next_reconcile_at": None})
                    return await self._finish(entry, "reconcile_not_placed")
            if exhausted:
                entry = entry.model_copy(update={"state": "NOT_PLACED", "next_reconcile_at": None,
                                                 "reason": f"the {entry.action.lower()} was not applied by 021"})
                return await self._finish(entry, "reconcile_not_placed")
        entry = self._schedule(entry, now)
        await self.store.update_journal(entry)
        return None
