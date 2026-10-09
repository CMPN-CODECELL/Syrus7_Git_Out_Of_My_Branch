"""
Execution service: the only code path that sends an order action to 021.

approve():
  1. owner, state, expiry and payload-hash checks
  2. kill switch, then pre_send_check (limits, instrument freshness, price drift, source quantity)
  3. store.claim(): PROPOSED -> APPROVED and journal row SENDING, atomically (one winner, ever)
  4. exactly one broker call, serialised with every other send
  5. journal outcome: ACKED | REJECTED | NOT_SENT | UNKNOWN (UNKNOWN goes to the reconciler)
"""
import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional

from app.config.settings import Settings, get_settings
from domains.broker.domain.errors import BrokerError, BrokerOutcomeUnknownError, BrokerRejectedError
from domains.orders.application.hub import UserHub
from domains.orders.ports import AuditSink, OrderStore
from shared.contracts.orders import JournalEntry, OrderProposal
from shared.logging.logger import get_correlation_id

logger = logging.getLogger(__name__)

FIRST_RECONCILE_DELAY = timedelta(seconds=2)


@dataclass
class ApproveOutcome:
    status: str               # sent | rejected | not_sent | unknown | requote | refused
    http_status: int
    message: str
    journal: Optional[JournalEntry] = None
    proposal: Optional[OrderProposal] = None
    new_proposal: Optional[OrderProposal] = None


PreSendCheck = Callable[[OrderProposal], Awaitable[object]]
Requote = Callable[[OrderProposal], Awaitable[Optional[OrderProposal]]]


class ExecutionService:
    def __init__(
        self,
        store: OrderStore,
        broker,
        audit: AuditSink,
        hub: UserHub,
        *,
        pre_send_check: PreSendCheck,
        requote: Optional[Requote] = None,
        on_unknown: Optional[Callable[[JournalEntry], None]] = None,
        settings: Callable[[], Settings] = get_settings,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self.store = store
        self.broker = broker
        self.audit = audit
        self.hub = hub
        self._check = pre_send_check
        self._requote = requote
        self._on_unknown = on_unknown
        self._settings = settings
        self._now = now
        self._send_lock = asyncio.Lock()

    async def _expire(self, p: OrderProposal, reason: str) -> None:
        if await self.store.transition_proposal(p.id, from_state="PROPOSED", to_state="EXPIRED", reason=reason, now=self._now()):
            await self.audit.record("proposal_expired", user_id=p.user_id, request_id=get_correlation_id(),
                                    proposal_id=p.id, data={"reason": reason})

    async def approve(self, proposal_id: uuid.UUID, user_id: str, payload_hash: str) -> ApproveOutcome:
        request_id = get_correlation_id()
        now = self._now()
        p = await self.store.get_proposal(proposal_id)
        if p is None or p.user_id != user_id:
            return ApproveOutcome("refused", 404, "Proposal not found.")
        await self.audit.record("approval_attempt", user_id=user_id, request_id=request_id, proposal_id=p.id,
                                data={"payload_hash": payload_hash})
        if p.state != "PROPOSED":
            return ApproveOutcome("refused", 409, f"This card was already {p.state.lower()}; it can't be approved again.", proposal=p)
        if p.expires_at <= now:
            await self._expire(p, "expired")
            return ApproveOutcome("refused", 410, "This card expired. Ask again for a fresh quote.", proposal=p)
        if payload_hash != p.payload_hash:
            return ApproveOutcome("refused", 409, "The order you approved doesn't match the stored proposal. Nothing was sent.", proposal=p)
        if self._settings().TradingKillSwitch:
            return ApproveOutcome("refused", 423, "Order sending is paused on this server (kill switch is on). Nothing was sent.", proposal=p)

        check = await self._check(p)
        if not check.ok:
            if check.requote:
                await self._expire(p, "price moved")
                new = await self._requote(p) if self._requote else None
                return ApproveOutcome("requote", 409, f"{check.reason} Nothing was sent; please review the new card.",
                                      proposal=p, new_proposal=new)
            await self._expire(p, check.reason)
            return ApproveOutcome("refused", 409, f"{check.reason} Nothing was sent.", proposal=p)

        journal = JournalEntry(proposal_id=p.id, user_id=user_id, action=p.kind, payload=p.payload, payload_hash=p.payload_hash,
                               target_order_id=p.target_order_id, state="SENDING", sent_at=now, updated_at=now, display=p.display,
                               order_id=p.target_order_id if p.kind != "PLACE" else None)
        claim = await self.store.claim(p.id, user_id, payload_hash, now, journal)
        if not claim.ok:
            messages = {"not_proposed": (409, "This card was already approved or closed."),
                        "expired": (410, "This card expired. Ask again for a fresh quote."),
                        "hash_mismatch": (409, "The approved order doesn't match the stored proposal."),
                        "not_found": (404, "Proposal not found."), "not_owner": (404, "Proposal not found.")}
            code, msg = messages[claim.failure or "not_found"]
            return ApproveOutcome("refused", code, msg + " Nothing was sent.", proposal=claim.proposal)
        await self.audit.record("proposal_approved", user_id=user_id, request_id=request_id, proposal_id=p.id, journal_id=journal.id,
                                data={"payload": p.payload.to_request_json(), "payload_hash": p.payload_hash})

        entry = await self._send(journal, request_id)
        await self.hub.publish_journal(entry)
        new = None
        if entry.state == "NOT_SENT" and self._requote:
            # 021 never processed it and this approval is spent: offer a fresh card for a new click.
            # Nothing is resent automatically.
            new = await self._requote(p)
        status, code, message = {
            "ACKED": ("sent", 200, "Sent to 021."),
            "REJECTED": ("rejected", 200, f"021 rejected the order: {entry.reason}"),
            "NOT_SENT": ("not_sent", 200, f"Not sent: {entry.reason}" + (" A fresh card is ready to approve." if new else " Ask again for a fresh card.")),
            "UNKNOWN": ("unknown", 200, "Sent, but 021 did not confirm. Kraken is checking the order book; it will not be resent."),
        }[entry.state]
        return ApproveOutcome(status, code, message, journal=entry, proposal=claim.proposal, new_proposal=new)

    async def _send(self, journal: JournalEntry, request_id: Optional[str]) -> JournalEntry:
        p = journal.payload
        async with self._send_lock:
            await self.audit.record("order_send", user_id=journal.user_id, request_id=request_id, proposal_id=journal.proposal_id,
                                    journal_id=journal.id, order_id=journal.target_order_id,
                                    data={"action": journal.action, "payload": p.to_request_json()})
            try:
                if journal.action == "PLACE":
                    order_id = await self.broker.place_order(p)
                    if not await self.store.link_order(journal.id, order_id):
                        logger.error("orderId %s already linked to another approval", order_id)
                    journal = journal.model_copy(update={"state": "ACKED", "order_id": order_id, "order_status": "Received"})
                elif journal.action == "MODIFY":
                    await self.broker.modify_order(journal.target_order_id, p)
                    journal = journal.model_copy(update={"state": "ACKED", "order_status": "SentForModification"})
                else:
                    await self.broker.cancel_order(journal.target_order_id, exchange=p.exchange, token=p.token, product=p.product)
                    journal = journal.model_copy(update={"state": "ACKED", "order_status": "SentForCancellation"})
            except BrokerRejectedError as exc:
                journal = journal.model_copy(update={"state": "REJECTED", "order_status": "Rejected", "reason": exc.message})
            except BrokerOutcomeUnknownError as exc:
                journal = journal.model_copy(update={"state": "UNKNOWN", "reason": exc.message,
                                                     "next_reconcile_at": self._now() + FIRST_RECONCILE_DELAY})
            except BrokerError as exc:
                # Every other broker error is raised before 021 processed the request.
                journal = journal.model_copy(update={"state": "NOT_SENT", "reason": exc.user_message()})
            except Exception as exc:  # unexpected: treat as unknown, never as "safe to resend"
                logger.exception("Unexpected error sending order")
                journal = journal.model_copy(update={"state": "UNKNOWN", "reason": f"unexpected {type(exc).__name__}",
                                                     "next_reconcile_at": self._now() + FIRST_RECONCILE_DELAY})
        await self.store.update_journal(journal)
        await self.audit.record("order_result", user_id=journal.user_id, request_id=request_id, proposal_id=journal.proposal_id,
                                journal_id=journal.id, order_id=journal.order_id,
                                data={"state": journal.state, "reason": journal.reason})
        if journal.state == "UNKNOWN" and self._on_unknown:
            self._on_unknown(journal)
        return (await self.store.get_journal(journal.id)) or journal
