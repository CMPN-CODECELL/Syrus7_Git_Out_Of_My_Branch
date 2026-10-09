import hashlib
import json
import uuid
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.contracts.instruments import RequestExchange

Book = Literal["RL", "SL"]
Product = Literal["INTRADAY", "CNC", "NRML"]
Validity = Literal["Day", "IOC"]


class OrderPayload(BaseModel):
    """The exact JSON body sent to 021 POST /orders or PUT /orders/{id}."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    exchange: RequestExchange
    token: int = Field(gt=0)
    qty: int
    price: int = Field(ge=0, description="Limit price in paise; 0 = market")
    book: Book = "RL"
    product: Product
    validity: Validity = "Day"
    trigger: Optional[int] = Field(None, gt=0)
    discQuantity: Optional[int] = Field(None, ge=0)
    amo: Optional[bool] = None

    @model_validator(mode="after")
    def _check(self) -> "OrderPayload":
        if self.qty == 0:
            raise ValueError("qty must be non-zero (sign is the side)")
        if self.book == "SL" and self.trigger is None:
            raise ValueError("SL orders need a trigger price")
        if self.book == "RL" and self.trigger is not None:
            raise ValueError("trigger is only valid on SL orders")
        if self.product == "CNC" and self.exchange not in ("NSE", "BSE"):
            raise ValueError("CNC is only valid for cash (NSE/BSE)")
        if self.product == "NRML" and self.exchange not in ("NSEFO", "BSEFO"):
            raise ValueError("NRML is only valid for F&O (NSEFO/BSEFO)")
        return self

    def to_request_json(self) -> dict:
        return self.model_dump(exclude_none=True)

    def canonical_bytes(self) -> bytes:
        return json.dumps(self.to_request_json(), sort_keys=True, separators=(",", ":")).encode()

    def payload_hash(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


class OrderDraft(BaseModel):
    """What the LLM may extract from a message. Never sent anywhere: the deterministic
    OrderBuilder resolves the instrument, parses prices from the raw text, and validates.
    Prices stay as the trader's text so the LLM never does money arithmetic."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["BUY", "SELL"]
    symbol_query: str = Field(min_length=1, max_length=64)
    quantity: Optional[int] = Field(None, gt=0)
    quantity_mode: Literal["UNITS", "LOTS", "HALF", "ALL"] = "UNITS"
    order_type: Literal["MARKET", "LIMIT", "SL"] = "MARKET"
    limit_price: Optional[str] = Field(None, max_length=32)
    trigger_price: Optional[str] = Field(None, max_length=32)
    product: Optional[Product] = None
    exchange_hint: Optional[Literal["NSE", "BSE"]] = None
    validity: Validity = "Day"
    instrument_kind: Literal["EQUITY", "OPTION", "FUTURE"] = "EQUITY"
    expiry: Optional[str] = Field(None, max_length=32)
    strike: Optional[str] = Field(None, max_length=32)
    option_type: Optional[Literal["CE", "PE"]] = None
    source: Optional[Literal["HOLDING", "POSITION"]] = None  # for HALF/ALL when both exist
    short: bool = False


class OrderChangeDraft(BaseModel):
    """Modify or cancel an existing open order, identified by description."""

    model_config = ConfigDict(extra="forbid")

    symbol_query: str = Field(min_length=1, max_length=64)
    side: Optional[Literal["BUY", "SELL"]] = None
    stop_loss_only: bool = False
    order_id: Optional[str] = Field(None, max_length=32)
    new_limit_price: Optional[str] = Field(None, max_length=32)
    new_trigger_price: Optional[str] = Field(None, max_length=32)
    new_quantity: Optional[int] = Field(None, gt=0)


class ProposalDisplay(BaseModel):
    """Everything the confirmation card shows. Rendered from these fields only, never LLM prose."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str
    exchange: str
    side: Literal["BUY", "SELL"]
    quantity: int = Field(gt=0)
    lots: Optional[int] = None
    lot_size: Optional[int] = None
    order_type: Literal["MARKET", "LIMIT", "SL"]
    product: Optional[Product] = None
    validity: Optional[Validity] = None
    limit_price_paise: Optional[int] = None
    trigger_price_paise: Optional[int] = None
    amo: bool = False
    action: Literal["PLACE", "MODIFY", "CANCEL"] = "PLACE"
    target_order_id: Optional[str] = None
    reference_ltp_paise: Optional[int] = None
    reference_ltp_as_of: Optional[datetime] = None
    estimated_value_paise: Optional[int] = None
    notices: list[str] = Field(default_factory=list)


ProposalState = Literal["PROPOSED", "APPROVED", "REJECTED", "EXPIRED"]


class OrderProposal(BaseModel):
    """A server-side, immutable proposal. Approval binds to payload_hash, is single-use and expires."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    user_id: str
    kind: Literal["PLACE", "MODIFY", "CANCEL"]
    payload: OrderPayload
    target_order_id: Optional[str] = None
    payload_hash: str
    display: ProposalDisplay
    created_at: datetime
    expires_at: datetime
    state: ProposalState = "PROPOSED"
    state_reason: Optional[str] = None
    decided_at: Optional[datetime] = None
    # What the builder saw, so approval can re-check it (drift, "sell half" source quantity).
    reference_ltp: Optional[int] = None
    source_check: Optional[dict[str, Any]] = None
    draft: Optional[dict[str, Any]] = None
    request_id: Optional[str] = None

    @model_validator(mode="after")
    def _hash_matches(self) -> "OrderProposal":
        if self.payload.payload_hash() != self.payload_hash:
            raise ValueError("payload_hash does not match payload")
        if self.kind != "PLACE" and not self.target_order_id:
            raise ValueError("MODIFY/CANCEL proposals need target_order_id")
        return self


JournalState = Literal["SENDING", "ACKED", "REJECTED", "NOT_SENT", "UNKNOWN", "NOT_PLACED", "AMBIGUOUS"]
FINAL_ORDER_STATUSES = frozenset({"Executed", "Rejected", "Cancelled"})


class JournalEntry(BaseModel):
    """One execution of one approved proposal. proposal_id is unique: a proposal can be sent once."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    proposal_id: uuid.UUID
    user_id: str
    action: Literal["PLACE", "MODIFY", "CANCEL"]
    payload: OrderPayload
    payload_hash: str
    target_order_id: Optional[str] = None
    state: JournalState = "SENDING"
    order_id: Optional[str] = None
    order_status: Optional[str] = None
    filled_qty: int = 0
    avg_fill_price: Optional[int] = None
    reason: Optional[str] = None
    sent_at: datetime
    updated_at: datetime
    reconcile_attempts: int = 0
    next_reconcile_at: Optional[datetime] = None
    display: Optional[ProposalDisplay] = None

    @property
    def unresolved(self) -> bool:
        return self.state in ("SENDING", "UNKNOWN")


OrderStatus = Literal[
    "Received", "Placed", "Pending", "Executed", "Rejected", "Cancelled", "Frozen",
    "SentForModification", "SentForCancellation", "AcceptedForAMO",
]

OrderSocketEvent = Literal[
    "TRADE", "ACCEPTED", "REJECTED", "SL_TRIGGERED", "MODIFY_ACCEPTED", "MODIFY_REJECTED",
    "CANCELLED", "CANCEL_REJECTED", "PRICE_CONFIRMATION",
]


class OrderEvent(BaseModel):
    """An order update, from the orders socket or a REST catch-up. Keyed by orderId."""

    model_config = ConfigDict(extra="forbid")

    order_id: str
    source: Literal["SOCKET", "REST"]
    event: Optional[OrderSocketEvent] = None
    status: Optional[OrderStatus] = None
    exchange_code: Optional[int] = None
    token: Optional[int] = None
    symbol: Optional[str] = None
    qty: Optional[int] = None
    price: Optional[int] = None
    reason: Optional[str] = None
    received_at: datetime
