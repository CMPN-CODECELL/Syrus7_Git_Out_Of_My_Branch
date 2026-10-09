"""Storage ports for proposals, the order journal and the audit trail."""
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Optional, Protocol

from shared.contracts.orders import JournalEntry, OrderProposal

ClaimFailure = Literal["not_found", "not_owner", "not_proposed", "expired", "hash_mismatch"]


@dataclass
class ClaimResult:
    ok: bool
    proposal: Optional[OrderProposal] = None
    journal: Optional[JournalEntry] = None
    failure: Optional[ClaimFailure] = None


class OrderStore(Protocol):
    async def save_proposal(self, proposal: OrderProposal) -> None: ...

    async def get_proposal(self, proposal_id: uuid.UUID) -> Optional[OrderProposal]: ...

    async def transition_proposal(self, proposal_id: uuid.UUID, *, from_state: str, to_state: str,
                                  reason: Optional[str], now: datetime) -> bool:
        """Compare-and-set the proposal state. True only for the caller that changed it."""
        ...

    async def claim(self, proposal_id: uuid.UUID, user_id: str, payload_hash: str, now: datetime,
                    journal: JournalEntry) -> ClaimResult:
        """Atomically PROPOSED -> APPROVED (owner, unexpired, hash match) and insert the journal row
        in state SENDING. At most one caller can ever succeed for a proposal."""
        ...

    async def get_journal(self, journal_id: uuid.UUID) -> Optional[JournalEntry]: ...

    async def update_journal(self, entry: JournalEntry) -> None: ...

    async def link_order(self, journal_id: uuid.UUID, order_id: str) -> bool:
        """Attach a 021 orderId to a PLACE journal row. False if that orderId is already linked
        to another PLACE row (one 021 order can never satisfy two approvals)."""
        ...

    async def list_journal(self, user_id: str, limit: int = 50) -> list[JournalEntry]: ...

    async def unresolved_journal(self) -> list[JournalEntry]: ...

    async def open_journal(self) -> list[JournalEntry]:
        """Rows linked to a 021 order whose status is not final yet."""
        ...

    async def journal_by_order_id(self, order_id: str) -> list[JournalEntry]: ...

    async def linked_place_order_ids(self) -> set[str]: ...

    async def latest_proposals(self, user_id: str, limit: int = 5) -> list[OrderProposal]: ...


class AuditSink(Protocol):
    async def record(self, kind: str, *, user_id: Optional[str] = None, request_id: Optional[str] = None,
                     proposal_id: Optional[uuid.UUID] = None, journal_id: Optional[uuid.UUID] = None,
                     order_id: Optional[str] = None, data: Optional[dict[str, Any]] = None) -> None: ...
