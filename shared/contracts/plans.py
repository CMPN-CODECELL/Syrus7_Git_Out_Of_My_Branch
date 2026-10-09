import hashlib
import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.contracts.orders import OrderPayload, ProposalDisplay

LegState = Literal["PENDING", "SENDING", "ACKED", "UNKNOWN", "EXECUTED", "PARTIAL", "REJECTED", "CANCELLED", "SKIPPED"]


class PlanLeg(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seq: int = Field(ge=0)
    payload: OrderPayload
    display: ProposalDisplay
    state: LegState = "PENDING"
    order_id: Optional[str] = None
    filled_qty: int = 0
    avg_fill_price: Optional[int] = None
    reason: Optional[str] = None


class Plan(BaseModel):
    """A multi-order plan approved once. plan_hash covers every leg's payload in order."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    user_id: str
    title: str = Field(max_length=200)
    legs: list[PlanLeg]
    plan_hash: str
    created_at: datetime
    expires_at: datetime
    state: Literal["PROPOSED", "APPROVED", "RUNNING", "DONE", "REJECTED", "EXPIRED"] = "PROPOSED"

    @staticmethod
    def compute_hash(legs: list[PlanLeg]) -> str:
        digest = hashlib.sha256()
        for leg in sorted(legs, key=lambda item: item.seq):
            digest.update(str(leg.seq).encode())
            digest.update(leg.payload.canonical_bytes())
        return digest.hexdigest()

    @model_validator(mode="after")
    def _hash_matches(self) -> "Plan":
        if self.compute_hash(self.legs) != self.plan_hash:
            raise ValueError("plan_hash does not match legs")
        return self
