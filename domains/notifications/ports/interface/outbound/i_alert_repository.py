from abc import ABC, abstractmethod
from typing import List, Optional
import uuid
from datetime import datetime

from domains.notifications.domain.entities import AlertRule, NotificationEvent


class IAlertRuleRepositoryPort(ABC):
    """Outbound port for AlertRule storage operations."""

    @abstractmethod
    async def save_rule(self, rule: AlertRule) -> AlertRule:
        """Persist a new or updated AlertRule."""
        pass

    @abstractmethod
    async def get_rule_by_id(self, rule_id: uuid.UUID) -> Optional[AlertRule]:
        """Fetch alert rule by ID."""
        pass

    @abstractmethod
    async def get_active_rules_by_symbol(self, symbol: str) -> List[AlertRule]:
        """Fetch active alert rules for a specific market symbol."""
        pass

    @abstractmethod
    async def delete_rule(self, rule_id: uuid.UUID) -> bool:
        """Delete alert rule by ID."""
        pass

    @abstractmethod
    async def update_last_triggered(
        self, rule_id: uuid.UUID, triggered_at: datetime
    ) -> None:
        """Update last_triggered_at timestamp for a rule."""
        pass

    @abstractmethod
    async def log_notification_event(self, event: NotificationEvent) -> NotificationEvent:
        """Persist notification dispatch log."""
        pass
