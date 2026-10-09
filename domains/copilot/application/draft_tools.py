"""
Draft tools for the LLM. They turn a request into a server-side proposal card, or a question,
or a refusal. They never send anything: sending happens only in ExecutionService.approve(),
reached by the trader clicking Approve on the card.
"""
import logging
from typing import Any, Optional

from domains.broker.domain.errors import BrokerError
from domains.copilot.application.order_builder import BuiltOrder, DraftProblem, OrderBuilder
from domains.orders.application.proposals import ProposalService
from shared.contracts.orders import OrderChangeDraft, OrderDraft, OrderProposal

logger = logging.getLogger(__name__)

CARD_NOTE = ("A confirmation card is now shown to the trader. Nothing is sent unless they click Approve on that card "
             "within its time limit. Do not say the order is placed or approved; typing 'yes' in chat does not approve it.")


class DraftToolbox:
    def __init__(self, builder: OrderBuilder, proposals: ProposalService):
        self.builder = builder
        self.proposals = proposals

    async def _propose(self, user_id: str, build) -> dict[str, Any]:
        try:
            built: BuiltOrder = await build
        except DraftProblem as problem:
            return {"status": problem.status, "message": problem.message, "options": problem.options}
        except BrokerError as exc:
            return {"status": "refused", "message": exc.user_message(), "options": []}
        proposal = await self.proposals.create(user_id, built)
        return {
            "status": "proposed",
            "proposal_id": str(proposal.id),
            "card": proposal.display.model_dump(mode="json"),
            "expires_in_seconds": int((proposal.expires_at - proposal.created_at).total_seconds()),
            "note": CARD_NOTE,
        }

    async def draft_order(self, user_id: str, args: OrderDraft) -> dict[str, Any]:
        return await self._propose(user_id, self.builder.build_place(args))

    async def draft_modify_order(self, user_id: str, args: OrderChangeDraft) -> dict[str, Any]:
        return await self._propose(user_id, self.builder.build_modify(args))

    async def draft_cancel_order(self, user_id: str, args: OrderChangeDraft) -> dict[str, Any]:
        return await self._propose(user_id, self.builder.build_cancel(args))

    async def requote(self, old: OrderProposal) -> Optional[OrderProposal]:
        """Rebuild an expired card (e.g. after a price move) from its original draft, at today's prices."""
        if not old.draft:
            return None
        try:
            if old.kind == "PLACE":
                built = await self.builder.build_place(OrderDraft.model_validate(old.draft))
            elif old.kind == "MODIFY":
                built = await self.builder.build_modify(OrderChangeDraft.model_validate(old.draft))
            else:
                built = await self.builder.build_cancel(OrderChangeDraft.model_validate(old.draft))
        except (DraftProblem, BrokerError) as exc:
            logger.info("re-quote failed: %s", exc)
            return None
        return await self.proposals.create(old.user_id, built)
