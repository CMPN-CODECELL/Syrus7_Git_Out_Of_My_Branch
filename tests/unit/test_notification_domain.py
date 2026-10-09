import uuid
from datetime import datetime, timedelta, timezone
import pytest

from domains.notifications.domain.value_objects import (
    ConditionType,
    DeliveryChannel,
    AlertStatus,
)
from domains.notifications.domain.entities import AlertRule, NotificationEvent
from domains.notifications.domain.exceptions import (
    NotificationDomainError,
    AlertRuleNotFoundError,
    NotificationDeliveryError,
)


def test_alert_rule_cooldown_active():
    """Verify alert rule cooldown triggers correctly when last_triggered_at is recent."""
    now = datetime.now(timezone.utc)
    rule = AlertRule(
        id=uuid.uuid4(),
        symbol="NIFTY",
        condition_type=ConditionType.ABOVE_PRICE,
        threshold=24000.0,
        channels=[DeliveryChannel.WEBSOCKET],
        cooldown_seconds=300,
        last_triggered_at=now - timedelta(seconds=100),  # Triggered 100s ago
        is_active=True,
    )
    assert rule.is_in_cooldown(now) is True


def test_alert_rule_cooldown_expired():
    """Verify alert rule cooldown allows trigger when cooldown period elapsed."""
    now = datetime.now(timezone.utc)
    rule = AlertRule(
        id=uuid.uuid4(),
        symbol="NIFTY",
        condition_type=ConditionType.ABOVE_PRICE,
        threshold=24000.0,
        channels=[DeliveryChannel.WEBSOCKET],
        cooldown_seconds=300,
        last_triggered_at=now - timedelta(seconds=350),  # Triggered 350s ago
        is_active=True,
    )
    assert rule.is_in_cooldown(now) is False


def test_alert_rule_never_triggered():
    """Verify alert rule is not in cooldown if never previously triggered."""
    now = datetime.now(timezone.utc)
    rule = AlertRule(
        id=uuid.uuid4(),
        symbol="BANKNIFTY",
        condition_type=ConditionType.IV_SPIKE,
        threshold=25.0,
        channels=[DeliveryChannel.WEBHOOK],
        cooldown_seconds=300,
        last_triggered_at=None,
        is_active=True,
    )
    assert rule.is_in_cooldown(now) is False


def test_inactive_alert_rule_cooldown():
    """Verify inactive rule is treated as in cooldown (blocked)."""
    now = datetime.now(timezone.utc)
    rule = AlertRule(
        id=uuid.uuid4(),
        symbol="NIFTY",
        condition_type=ConditionType.ABOVE_PRICE,
        threshold=24000.0,
        channels=[DeliveryChannel.WEBSOCKET],
        cooldown_seconds=300,
        last_triggered_at=None,
        is_active=False,
    )
    assert rule.is_in_cooldown(now) is True


def test_notification_event_creation():
    """Verify NotificationEvent entity default fields."""
    event_id = uuid.uuid4()
    rule_id = uuid.uuid4()
    event = NotificationEvent(
        id=event_id,
        rule_id=rule_id,
        symbol="NIFTY",
        condition_type=ConditionType.ABOVE_PRICE,
        triggered_value=24100.0,
        threshold=24000.0,
        message="NIFTY crossed 24000 threshold",
        channels=[DeliveryChannel.WEBSOCKET, DeliveryChannel.EMAIL],
    )
    assert event.status == AlertStatus.PENDING
    assert event.error_message is None
    assert event.triggered_value == 24100.0


def test_notification_domain_exceptions():
    """Verify exception hierarchy inheritance."""
    assert issubclass(AlertRuleNotFoundError, NotificationDomainError)
    assert issubclass(NotificationDeliveryError, NotificationDomainError)
