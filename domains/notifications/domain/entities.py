from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional
import uuid

from domains.notifications.domain.value_objects import (
    ConditionType,
    DeliveryChannel,
    AlertStatus,
)


@dataclass
class AlertRule:
    """Aggregate Root representing a user-configured notification trigger rule."""
    id: uuid.UUID
    symbol: str
    condition_type: ConditionType
    threshold: float
    channels: List[DeliveryChannel]
    cooldown_seconds: int = 300
    last_triggered_at: Optional[datetime] = None
    is_active: bool = True
    webhook_url: Optional[str] = None
    email_destination: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def is_in_cooldown(self, current_time: datetime) -> bool:
        """Check if rule is active and outside cooldown period."""
        if not self.is_active:
            return True
        if self.last_triggered_at is None:
            return False
        elapsed = (current_time - self.last_triggered_at).total_seconds()
        return elapsed < self.cooldown_seconds


@dataclass
class NotificationEvent:
    """Entity representing an executed notification instance."""
    id: uuid.UUID
    rule_id: uuid.UUID
    symbol: str
    condition_type: ConditionType
    triggered_value: float
    threshold: float
    message: str
    channels: List[DeliveryChannel]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: AlertStatus = AlertStatus.PENDING
    error_message: Optional[str] = None
