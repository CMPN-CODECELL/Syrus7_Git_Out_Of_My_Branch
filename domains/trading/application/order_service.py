import logging
from typing import Dict, Any, Optional
import uuid

from domains.trading.infrastructure.outbound.trade_client import Zero21TradeClient
from domains.copilot.domain.entities import ReasoningOutput, RecommendationDecision

logger = logging.getLogger(__name__)

class OrderManagementService:
    """
    Manages the lifecycle of an order from AI proposal to execution.
    Enforces the 'Human-in-the-Loop' safety boundary: no trade executes
    without explicit confirmation.
    """
    def __init__(self, trade_client: Zero21TradeClient):
        self.trade_client = trade_client
        # In a real app, this would be a DB repository. Using a dict for POC.
        self._pending_proposals: Dict[str, Dict[str, Any]] = {}

    async def stage_order_proposal(self, reasoning_result: ReasoningOutput) -> str:
        """
        Takes the output from the AI Reasoning Layer and stages an order.
        Returns a proposal_id that the UI will use to confirm.
        """
        if not reasoning_result.proposed_order_payload:
            raise ValueError("No proposed order payload found in reasoning result.")

        proposal_id = str(uuid.uuid4())
        
        self._pending_proposals[proposal_id] = {
            "status": "PENDING_APPROVAL",
            "payload": reasoning_result.proposed_order_payload,
            "decision": reasoning_result.decision,
            "justification": reasoning_result.human_readable_summary,
            "original_intent": reasoning_result.original_intent
        }
        
        logger.info(f"Staged order proposal {proposal_id} for user approval.")
        return proposal_id

    def get_staged_proposal(self, proposal_id: str) -> Optional[Dict[str, Any]]:
        return self._pending_proposals.get(proposal_id)

    async def execute_approved_order(self, proposal_id: str) -> Dict[str, Any]:
        """
        Called by the frontend when the user clicks 'Confirm' on the order preview.
        """
        proposal = self._pending_proposals.get(proposal_id)
        if not proposal:
            raise ValueError(f"Proposal {proposal_id} not found or expired.")
            
        if proposal["status"] != "PENDING_APPROVAL":
            raise ValueError(f"Proposal {proposal_id} cannot be executed (Status: {proposal['status']})")
            
        payload = proposal["payload"]
        logger.info(f"User approved proposal {proposal_id}. Sending to exchange...")
        
        try:
            # For "golden zone" limit orders, the payload book is 'RL', meaning 
            # the exchange keeps it ready and auto-executes when the price hits.
            result = await self.trade_client.place_order(payload)
            
            proposal["status"] = "EXECUTED"
            proposal["exchange_order_id"] = result.get("orderId")
            
            logger.info(f"Successfully executed proposal {proposal_id}.")
            return result
        except Exception as e:
            proposal["status"] = "FAILED"
            logger.error(f"Failed to execute approved order {proposal_id}: {str(e)}")
            raise e
