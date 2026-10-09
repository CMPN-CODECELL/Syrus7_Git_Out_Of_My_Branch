import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock
import pytest

from domains.notifications.domain.entities import AlertRule
from domains.notifications.domain.value_objects import (
    ConditionType,
    DeliveryChannel,
    AlertStatus,
)
from domains.notifications.domain.services.rule_matcher import RuleMatcherDomainService
from domains.notifications.application.evaluate_alerts_service import EvaluateAlertsService
from domains.notifications.ports.interface.outbound.i_notification_channel import (
    INotificationChannelAdapterPort,
)


def test_rule_matcher_above_price_match():
    rule = AlertRule(
        id=uuid.uuid4(),
        symbol="NIFTY",
        condition_type=ConditionType.ABOVE_PRICE,
        threshold=24000.0,
        channels=[DeliveryChannel.WEBSOCKET],
    )
    payload = {"spot_price": 24150.0}
    matched, val, msg = RuleMatcherDomainService.match(rule, payload)
    assert matched is True
    assert val == 24150.0
    assert "crossed above threshold" in msg


def test_rule_matcher_below_price_no_match():
    rule = AlertRule(
        id=uuid.uuid4(),
        symbol="NIFTY",
        condition_type=ConditionType.BELOW_PRICE,
        threshold=24000.0,
        channels=[DeliveryChannel.WEBSOCKET],
    )
    payload = {"spot_price": 24150.0}
    matched, val, msg = RuleMatcherDomainService.match(rule, payload)
    assert matched is False
    assert val is None
    assert msg is None


def test_rule_matcher_iv_spike_match():
    rule = AlertRule(
        id=uuid.uuid4(),
        symbol="BANKNIFTY",
        condition_type=ConditionType.IV_SPIKE,
        threshold=20.0,
        channels=[DeliveryChannel.WEBHOOK],
    )
    payload = {"implied_volatility": 25.5}
    matched, val, msg = RuleMatcherDomainService.match(rule, payload)
    assert matched is True
    assert val == 25.5
    assert "spiked above threshold" in msg


def test_rule_matcher_delta_breach():
    rule = AlertRule(
        id=uuid.uuid4(),
        symbol="NIFTY",
        condition_type=ConditionType.DELTA_BREACH,
        threshold=0.5,
        channels=[DeliveryChannel.WEBSOCKET],
    )
    payload = {"delta": 0.65}
    matched, val, msg = RuleMatcherDomainService.match(rule, payload)
    assert matched is True
    assert val == 0.65


@pytest.mark.asyncio
async def test_evaluate_alerts_service_triggers():
    mock_repo = AsyncMock()
    mock_channel = AsyncMock(spec=INotificationChannelAdapterPort)
    mock_channel.dispatch.return_value = True

    rule = AlertRule(
        id=uuid.uuid4(),
        symbol="NIFTY",
        condition_type=ConditionType.ABOVE_PRICE,
        threshold=24000.0,
        channels=[DeliveryChannel.WEBSOCKET],
        cooldown_seconds=300,
        last_triggered_at=None,
        is_active=True,
    )
    mock_repo.get_active_rules_by_symbol.return_value = [rule]

    service = EvaluateAlertsService(repository=mock_repo, channels=[mock_channel])
    events = await service.evaluate_tick_event("NIFTY", {"spot_price": 24200.0})

    assert len(events) == 1
    assert events[0].triggered_value == 24200.0
    assert events[0].status == AlertStatus.DELIVERED
    assert mock_channel.dispatch.called
    assert mock_repo.update_last_triggered.called
    assert mock_repo.log_notification_event.called
