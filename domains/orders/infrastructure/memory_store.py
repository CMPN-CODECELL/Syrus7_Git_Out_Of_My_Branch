"""In-memory OrderStore / AuditSink with the same atomic semantics as the Postgres store.
Used by tests. Not used in production: a restart would lose proposals and the journal."""
import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from domains.orders.ports import ClaimResult
from shared.contracts.orders import FINAL_ORDER_STATUSES, JournalEntry, OrderProposal


class MemoryOrderStore:
    def __init__(self) -> None:
        self._proposals: dict[uuid.UUID, OrderProposal] = {}
        self._journal: dict[uuid.UUID, JournalEntry] = {}
        self._lock = asyncio.Lock()

    async def save_proposal(self, proposal: OrderProposal) -> None:
        async with self._lock:
            self._proposals[proposal.id] = proposal.model_copy(deep=True)

    async def get_proposal(self, proposal_id: uuid.UUID) -> Optional[OrderProposal]:
        p = self._proposals.get(proposal_id)
        return p.model_copy(deep=True) if p else None

    async def transition_proposal(self, proposal_id, *, from_state, to_state, reason, now) -> bool:
        async with self._lock:
            p = self._proposals.get(proposal_id)
            if p is None or p.state != from_state:
                return False
            self._proposals[proposal_id] = p.model_copy(update={"state": to_state, "state_reason": reason, "decided_at": now})
            return True

    async def claim(self, proposal_id, user_id, payload_hash, now, journal) -> ClaimResult:
        async with self._lock:
            p = self._proposals.get(proposal_id)
            if p is None:
                return ClaimResult(False, failure="not_found")
            if p.user_id != user_id:
                return ClaimResult(False, failure="not_owner")
            if p.state != "PROPOSED":
                return ClaimResult(False, proposal=p, failure="not_proposed")
            if p.expires_at <= now:
                return ClaimResult(False, proposal=p, failure="expired")
            if p.payload_hash != payload_hash:
                return ClaimResult(False, proposal=p, failure="hash_mismatch")
            if any(j.proposal_id == proposal_id for j in self._journal.values()):
                return ClaimResult(False, proposal=p, failure="not_proposed")
            approved = p.model_copy(update={"state": "APPROVED", "decided_at": now})
            self._proposals[proposal_id] = approved
            self._journal[journal.id] = journal.model_copy(deep=True)
            return ClaimResult(True, proposal=approved, journal=journal.model_copy(deep=True))

    async def get_journal(self, journal_id) -> Optional[JournalEntry]:
        j = self._journal.get(journal_id)
        return j.model_copy(deep=True) if j else None

    async def update_journal(self, entry: JournalEntry) -> None:
        async with self._lock:
            self._journal[entry.id] = entry.model_copy(deep=True, update={"updated_at": datetime.now(timezone.utc)})

    async def link_order(self, journal_id, order_id: str) -> bool:
        async with self._lock:
            entry = self._journal.get(journal_id)
            if entry is None:
                return False
            if any(j.order_id == order_id and j.action == "PLACE" and j.id != journal_id for j in self._journal.values()):
                return False
            self._journal[journal_id] = entry.model_copy(update={"order_id": order_id})
            return True

    async def list_journal(self, user_id: str, limit: int = 50) -> list[JournalEntry]:
        rows = [j for j in self._journal.values() if j.user_id == user_id]
        rows.sort(key=lambda j: j.sent_at, reverse=True)
        return [j.model_copy(deep=True) for j in rows[:limit]]

    async def unresolved_journal(self) -> list[JournalEntry]:
        return [j.model_copy(deep=True) for j in self._journal.values() if j.unresolved]

    async def open_journal(self) -> list[JournalEntry]:
        return [j.model_copy(deep=True) for j in self._journal.values()
                if j.order_id and j.state == "ACKED" and j.order_status not in FINAL_ORDER_STATUSES]

    async def journal_by_order_id(self, order_id: str) -> list[JournalEntry]:
        return [j.model_copy(deep=True) for j in self._journal.values() if j.order_id == order_id]

    async def linked_place_order_ids(self) -> set[str]:
        return {j.order_id for j in self._journal.values() if j.order_id and j.action == "PLACE"}

    async def latest_proposals(self, user_id: str, limit: int = 5) -> list[OrderProposal]:
        rows = sorted((p for p in self._proposals.values() if p.user_id == user_id), key=lambda p: p.created_at, reverse=True)
        return [p.model_copy(deep=True) for p in rows[:limit]]

    # test helper
    def all_journal(self) -> list[JournalEntry]:
        return list(self._journal.values())


class MemoryAuditSink:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def record(self, kind, *, user_id=None, request_id=None, proposal_id=None, journal_id=None, order_id=None, data=None) -> None:
        self.events.append({
            "at": datetime.now(timezone.utc), "kind": kind, "user_id": user_id, "request_id": request_id,
            "proposal_id": proposal_id, "journal_id": journal_id, "order_id": order_id, "data": data or {},
        })

    def kinds(self) -> list[str]:
        return [e["kind"] for e in self.events]
