from typing import List, Optional
from pydantic import BaseModel, Field
import uuid
from datetime import datetime

from domains.notifications.domain.value_objects import (
    ConditionType,
    DeliveryChannel,
    AlertStatus,
)


class CreateAlertRuleRequest(BaseModel):
    symbol: str = Field(..., json_schema_extra={"example": "NIFTY"}, description="Market symbol")
    condition_type: ConditionType = Field(..., description="Condition type enum")
    threshold: float = Field(..., description="Trigger threshold value")
    channels: List[DeliveryChannel] = Field(default=[DeliveryChannel.WEBSOCKET], description="Delivery channels")
    cooldown_seconds: int = Field(default=300, ge=10, description="Minimum seconds between triggers")
    webhook_url: Optional[str] = Field(default=None, description="Optional HTTP Webhook URL")
    email_destination: Optional[str] = Field(default=None, description="Optional destination email address")


class AlertRuleResponse(BaseModel):
    id: uuid.UUID
    symbol: str
    condition_type: ConditionType
    threshold: float
    channels: List[DeliveryChannel]
    cooldown_seconds: int
    last_triggered_at: Optional[datetime] = None
    is_active: bool
    webhook_url: Optional[str] = None
    email_destination: Optional[str] = None
    created_at: datetime


class NotificationLogResponse(BaseModel):
    id: uuid.UUID
    rule_id: uuid.UUID
    symbol: str
    condition_type: ConditionType
    triggered_value: float
    threshold: float
    message: str
    channels: List[DeliveryChannel]
    status: AlertStatus
    error_message: Optional[str] = None
    timestamp: datetime
