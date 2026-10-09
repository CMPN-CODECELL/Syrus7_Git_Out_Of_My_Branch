import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import pytest

from domains.notifications.domain.entities import AlertRule, NotificationEvent
from domains.notifications.domain.value_objects import (
    ConditionType,
    DeliveryChannel,
    AlertStatus,
)
from domains.notifications.infrastructure.persistence.alert_repository import (
    PostgresAlertRuleRepository,
)


@pytest.fixture
def mock_db_pool():
    """Mock asyncpg connection pool for repository unit/integration tests."""
    pool = MagicMock()
    conn = AsyncMock()
    
    # Setup context manager for async with pool.acquire() as conn:
    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=None)
    pool.acquire.return_value = acquire_cm
    
    return pool, conn


@pytest.mark.asyncio
async def test_save_rule(mock_db_pool):
    pool, conn = mock_db_pool
    repo = PostgresAlertRuleRepository(pool=pool)
    
    rule = AlertRule(
        id=uuid.uuid4(),
        symbol="NIFTY",
        condition_type=ConditionType.ABOVE_PRICE,
        threshold=24500.0,
        channels=[DeliveryChannel.WEBSOCKET, DeliveryChannel.EMAIL],
        cooldown_seconds=300,
        is_active=True,
    )
    
    saved_rule = await repo.save_rule(rule)
    assert saved_rule.id == rule.id
    assert conn.execute.called
    args = conn.execute.call_args[0]
    assert "INSERT INTO AlertRules" in args[0]
    assert args[1] == rule.id
    assert args[2] == "NIFTY"


@pytest.mark.asyncio
async def test_get_rule_by_id_found(mock_db_pool):
    pool, conn = mock_db_pool
    repo = PostgresAlertRuleRepository(pool=pool)
    
    rule_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    
    conn.fetchrow.return_value = {
        "id": rule_id,
        "symbol": "BANKNIFTY",
        "condition_type": "IV_SPIKE",
        "threshold": 30.0,
        "channels": ["WEBSOCKET", "WEBHOOK"],
        "cooldown_seconds": 600,
        "last_triggered_at": None,
        "is_active": True,
        "webhook_url": "https://example.com/webhook",
        "email_destination": None,
        "created_at": now,
    }
    
    result = await repo.get_rule_by_id(rule_id)
    assert result is not None
    assert result.id == rule_id
    assert result.symbol == "BANKNIFTY"
    assert result.condition_type == ConditionType.IV_SPIKE
    assert DeliveryChannel.WEBSOCKET in result.channels


@pytest.mark.asyncio
async def test_get_rule_by_id_not_found(mock_db_pool):
    pool, conn = mock_db_pool
    repo = PostgresAlertRuleRepository(pool=pool)
    
    conn.fetchrow.return_value = None
    result = await repo.get_rule_by_id(uuid.uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_get_active_rules_by_symbol(mock_db_pool):
    pool, conn = mock_db_pool
    repo = PostgresAlertRuleRepository(pool=pool)
    
    now = datetime.now(timezone.utc)
    conn.fetch.return_value = [
        {
            "id": uuid.uuid4(),
            "symbol": "NIFTY",
            "condition_type": "ABOVE_PRICE",
            "threshold": 24000.0,
            "channels": ["WEBSOCKET"],
            "cooldown_seconds": 300,
            "last_triggered_at": None,
            "is_active": True,
            "webhook_url": None,
            "email_destination": None,
            "created_at": now,
        }
    ]
    
    rules = await repo.get_active_rules_by_symbol("NIFTY")
    assert len(rules) == 1
    assert rules[0].symbol == "NIFTY"


@pytest.mark.asyncio
async def test_delete_rule(mock_db_pool):
    pool, conn = mock_db_pool
    repo = PostgresAlertRuleRepository(pool=pool)
    
    conn.execute.return_value = "DELETE 1"
    success = await repo.delete_rule(uuid.uuid4())
    assert success is True


@pytest.mark.asyncio
async def test_log_notification_event(mock_db_pool):
    pool, conn = mock_db_pool
    repo = PostgresAlertRuleRepository(pool=pool)
    
    event = NotificationEvent(
        id=uuid.uuid4(),
        rule_id=uuid.uuid4(),
        symbol="NIFTY",
        condition_type=ConditionType.ABOVE_PRICE,
        triggered_value=24100.0,
        threshold=24000.0,
        message="NIFTY crossed threshold",
        channels=[DeliveryChannel.WEBSOCKET],
        status=AlertStatus.PENDING,
    )
    
    logged = await repo.log_notification_event(event)
    assert logged.id == event.id
    assert conn.execute.called
    args = conn.execute.call_args[0]
    assert "INSERT INTO NotificationLogs" in args[0]
