"""Creates and serves order proposals. A proposal is immutable once saved; only its state changes."""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from domains.orders.ports import AuditSink, OrderStore
from shared.contracts.orders import OrderProposal
from shared.logging.logger import get_correlation_id

PROPOSAL_TTL_SECONDS = 60


def proposal_view(p: OrderProposal, now: datetime) -> dict[str, Any]:
    return {
        "proposal_id": str(p.id),
        "kind": p.kind,
        "state": p.state,
        "state_reason": p.state_reason,
        "card": p.display.model_dump(mode="json"),
        "payload": p.payload.to_request_json(),
        "payload_hash": p.payload_hash,
        "target_order_id": p.target_order_id,
        "created_at": p.created_at.isoformat(),
        "expires_at": p.expires_at.isoformat(),
        "seconds_left": max(0, int((p.expires_at - now).total_seconds())) if p.state == "PROPOSED" else 0,
    }


class ProposalService:
    def __init__(self, store: OrderStore, audit: AuditSink, *, ttl_seconds: int = PROPOSAL_TTL_SECONDS,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.store = store
        self.audit = audit
        self.ttl = timedelta(seconds=ttl_seconds)
        self.now = now

    async def create(self, user_id: str, built) -> OrderProposal:
        now = self.now()
        proposal = OrderProposal(
            user_id=user_id, kind=built.kind, payload=built.payload, payload_hash=built.payload.payload_hash(),
            display=built.display, target_order_id=built.target_order_id, created_at=now, expires_at=now + self.ttl,
            reference_ltp=built.reference_ltp, source_check=built.source_check, draft=built.draft,
            request_id=get_correlation_id(),
        )
        await self.store.save_proposal(proposal)
        await self.audit.record("proposal_created", user_id=user_id, request_id=proposal.request_id, proposal_id=proposal.id,
                                data={"kind": proposal.kind, "payload": proposal.payload.to_request_json(),
                                      "payload_hash": proposal.payload_hash})
        return proposal

    async def get_for_user(self, proposal_id: uuid.UUID, user_id: str) -> Optional[OrderProposal]:
        p = await self.store.get_proposal(proposal_id)
        if p is None or p.user_id != user_id:
            return None
        now = self.now()
        if p.state == "PROPOSED" and p.expires_at <= now:
            if await self.store.transition_proposal(p.id, from_state="PROPOSED", to_state="EXPIRED", reason="expired", now=now):
                await self.audit.record("proposal_expired", user_id=user_id, proposal_id=p.id)
            p = await self.store.get_proposal(proposal_id)
        return p

    async def reject(self, proposal_id: uuid.UUID, user_id: str) -> Optional[OrderProposal]:
        p = await self.get_for_user(proposal_id, user_id)
        if p is None:
            return None
        if p.state == "PROPOSED" and await self.store.transition_proposal(
                p.id, from_state="PROPOSED", to_state="REJECTED", reason="rejected by trader", now=self.now()):
            await self.audit.record("proposal_rejected", user_id=user_id, request_id=get_correlation_id(), proposal_id=p.id)
        return await self.store.get_proposal(proposal_id)
