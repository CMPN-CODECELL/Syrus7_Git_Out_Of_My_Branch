"""
Kraken shared contracts. Every module that crosses a team seam speaks these models.

Rules:
- Every price is an int in paise (Rs 1 = 100). Rupee formatting happens only in the UI.
- Quantity sign is the side: positive = buy, negative = sell.
- Models forbid unknown fields so LLM or third-party output cannot smuggle extra keys in.
"""
from shared.contracts.instruments import (
    EXCHANGE_TO_REQUEST,
    EXCHANGE_TO_WS_CODE,
    WS_CODE_TO_EXCHANGE,
    Instrument,
)
from shared.contracts.orders import (
    FINAL_ORDER_STATUSES,
    JournalEntry,
    OrderChangeDraft,
    OrderDraft,
    OrderEvent,
    OrderPayload,
    OrderProposal,
    ProposalDisplay,
)
from shared.contracts.plans import Plan, PlanLeg
from shared.contracts.instructions import StandingInstruction, TriggerCondition
from shared.contracts.market import PriceQuote

__all__ = [
    "EXCHANGE_TO_REQUEST",
    "EXCHANGE_TO_WS_CODE",
    "WS_CODE_TO_EXCHANGE",
    "Instrument",
    "FINAL_ORDER_STATUSES",
    "JournalEntry",
    "OrderChangeDraft",
    "OrderDraft",
    "OrderEvent",
    "OrderPayload",
    "OrderProposal",
    "ProposalDisplay",
    "Plan",
    "PlanLeg",
    "StandingInstruction",
    "TriggerCondition",
    "PriceQuote",
]
