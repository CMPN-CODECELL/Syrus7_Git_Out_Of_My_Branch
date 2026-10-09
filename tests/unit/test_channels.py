import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
import pytest

from domains.notifications.domain.entities import AlertRule, NotificationEvent
from domains.notifications.domain.value_objects import ConditionType, DeliveryChannel, AlertStatus
from domains.notifications.infrastructure.channels.websocket_channel import WebSocketNotificationChannelAdapter
from domains.notifications.infrastructure.channels.webhook_channel import WebhookNotificationChannelAdapter


@pytest.mark.asyncio
async def test_websocket_channel_dispatch():
    mock_bus = AsyncMock()
    mock_bus.publish.return_value = 1

    adapter = WebSocketNotificationChannelAdapter(event_bus=mock_bus)
    rule = AlertRule(
        id=uuid.uuid4(),
        symbol="NIFTY",
        condition_type=ConditionType.ABOVE_PRICE,
        threshold=24000.0,
        channels=[DeliveryChannel.WEBSOCKET],
    )
    event = NotificationEvent(
        id=uuid.uuid4(),
        rule_id=rule.id,
        symbol="NIFTY",
        condition_type=ConditionType.ABOVE_PRICE,
        triggered_value=24100.0,
        threshold=24000.0,
        message="NIFTY crossed 24000 threshold",
        channels=[DeliveryChannel.WEBSOCKET],
        timestamp=datetime.now(timezone.utc),
    )

    success = await adapter.dispatch(event, rule)
    assert success is True
    assert mock_bus.publish.called
    args = mock_bus.publish.call_args[0]
    assert "alerts.dispatched.NIFTY" in args[0]
    assert args[1]["symbol"] == "NIFTY"


@pytest.mark.asyncio
async def test_webhook_channel_missing_url():
    adapter = WebhookNotificationChannelAdapter()
    rule = AlertRule(
        id=uuid.uuid4(),
        symbol="NIFTY",
        condition_type=ConditionType.ABOVE_PRICE,
        threshold=24000.0,
        channels=[DeliveryChannel.WEBHOOK],
        webhook_url=None,
    )
    event = NotificationEvent(
        id=uuid.uuid4(),
        rule_id=rule.id,
        symbol="NIFTY",
        condition_type=ConditionType.ABOVE_PRICE,
        triggered_value=24100.0,
        threshold=24000.0,
        message="NIFTY crossed threshold",
        channels=[DeliveryChannel.WEBHOOK],
    )

    success = await adapter.dispatch(event, rule)
    assert success is False
