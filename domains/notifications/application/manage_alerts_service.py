from typing import List, Optional
import uuid
import logging

from domains.notifications.domain.entities import AlertRule
from domains.notifications.domain.exceptions import AlertRuleNotFoundError
from domains.notifications.ports.interface.inbound.i_manage_alerts import (
    IManageAlertRulesUseCasePort,
)
from domains.notifications.ports.interface.outbound.i_alert_repository import (
    IAlertRuleRepositoryPort,
)

logger = logging.getLogger(__name__)


class ManageAlertRulesService(IManageAlertRulesUseCasePort):
    """Application service orchestrating AlertRule creation, queries, and deletion."""

    def __init__(self, repository: IAlertRuleRepositoryPort):
        self._repo = repository

    async def create_rule(self, rule: AlertRule) -> AlertRule:
        logger.info(f"Creating alert rule {rule.id} for symbol {rule.symbol}")
        return await self._repo.save_rule(rule)

    async def get_rule(self, rule_id: uuid.UUID) -> Optional[AlertRule]:
        rule = await self._repo.get_rule_by_id(rule_id)
        if not rule:
            raise AlertRuleNotFoundError(f"Alert rule {rule_id} not found")
        return rule

    async def list_active_rules(self, symbol: Optional[str] = None) -> List[AlertRule]:
        if symbol:
            return await self._repo.get_active_rules_by_symbol(symbol)
        # Fetch for empty symbol yields empty list
        return await self._repo.get_active_rules_by_symbol(symbol="")

    async def delete_rule(self, rule_id: uuid.UUID) -> bool:
        logger.info(f"Deleting alert rule {rule_id}")
        deleted = await self._repo.delete_rule(rule_id)
        if not deleted:
            raise AlertRuleNotFoundError(f"Alert rule {rule_id} not found")
        return True
