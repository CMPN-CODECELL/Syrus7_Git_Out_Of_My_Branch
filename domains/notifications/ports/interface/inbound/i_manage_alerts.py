from abc import ABC, abstractmethod
from typing import List, Optional
import uuid

from domains.notifications.domain.entities import AlertRule


class IManageAlertRulesUseCasePort(ABC):
    """Inbound port for managing user alert rules."""

    @abstractmethod
    async def create_rule(self, rule: AlertRule) -> AlertRule:
        """Create new alert rule."""
        pass

    @abstractmethod
    async def get_rule(self, rule_id: uuid.UUID) -> Optional[AlertRule]:
        """Fetch rule by ID."""
        pass

    @abstractmethod
    async def list_active_rules(self, symbol: Optional[str] = None) -> List[AlertRule]:
        """List active alert rules optionally filtered by symbol."""
        pass

    @abstractmethod
    async def delete_rule(self, rule_id: uuid.UUID) -> bool:
        """Delete alert rule."""
        pass
