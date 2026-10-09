import uuid
from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient

from app.main import app
from domains.notifications.domain.entities import AlertRule
from domains.notifications.domain.value_objects import ConditionType, DeliveryChannel
from domains.notifications.api.router import get_manage_alerts_service
from domains.notifications.application.manage_alerts_service import ManageAlertRulesService


@pytest.fixture
def mock_manage_service():
    service = AsyncMock(spec=ManageAlertRulesService)
    return service


def test_create_alert_rule_endpoint(mock_manage_service):
    rule_id = uuid.uuid4()
    mock_manage_service.create_rule.return_value = AlertRule(
        id=rule_id,
        symbol="NIFTY",
        condition_type=ConditionType.ABOVE_PRICE,
        threshold=24500.0,
        channels=[DeliveryChannel.WEBSOCKET],
        cooldown_seconds=300,
        is_active=True,
    )

    app.dependency_overrides[get_manage_alerts_service] = lambda: mock_manage_service

    client = TestClient(app)
    payload = {
        "symbol": "NIFTY",
        "condition_type": "ABOVE_PRICE",
        "threshold": 24500.0,
        "channels": ["WEBSOCKET"],
        "cooldown_seconds": 300,
    }

    resp = client.post(
        "/v1/notifications/alerts",
        json=payload,
        headers={"Authorization": "Bearer test-jwt-token"}
    )
    app.dependency_overrides.clear()

    assert resp.status_code == 201
    data = resp.json()
    assert data["symbol"] == "NIFTY"
    assert data["condition_type"] == "ABOVE_PRICE"
    assert data["threshold"] == 24500.0


def test_create_alert_rule_unauthenticated_fails(mock_manage_service):
    app.dependency_overrides[get_manage_alerts_service] = lambda: mock_manage_service
    client = TestClient(app)
    payload = {
        "symbol": "NIFTY",
        "condition_type": "ABOVE_PRICE",
        "threshold": 24500.0,
        "channels": ["WEBSOCKET"],
    }
    resp = client.post("/v1/notifications/alerts", json=payload)
    app.dependency_overrides.clear()
    assert resp.status_code == 401


def test_list_alert_rules_endpoint(mock_manage_service):
    mock_manage_service.list_active_rules.return_value = [
        AlertRule(
            id=uuid.uuid4(),
            symbol="BANKNIFTY",
            condition_type=ConditionType.IV_SPIKE,
            threshold=25.0,
            channels=[DeliveryChannel.WEBHOOK],
            is_active=True,
        )
    ]

    app.dependency_overrides[get_manage_alerts_service] = lambda: mock_manage_service
    client = TestClient(app)

    resp = client.get("/v1/notifications/alerts?symbol=BANKNIFTY")
    app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["symbol"] == "BANKNIFTY"
