import json
from unittest.mock import AsyncMock, patch
import pytest

from domains.notifications.infrastructure.subscribers.notification_subscriber import NotificationStreamSubscriber


@pytest.mark.asyncio
async def test_notification_subscriber_process_event():
    mock_redis = AsyncMock()
    mock_repo = AsyncMock()
    mock_repo.get_active_rules_by_symbol.return_value = []

    subscriber = NotificationStreamSubscriber(redis_client=mock_redis, repository=mock_repo)

    raw_payload = {
        b"data": json.dumps({
            "symbol": "NIFTY",
            "spot_price": 24200.0,
            "implied_volatility": 15.2,
        }).encode("utf-8")
    }

    await subscriber.process_event(raw_payload)
    assert mock_repo.get_active_rules_by_symbol.called
    assert mock_repo.get_active_rules_by_symbol.call_args[0][0] == "NIFTY"
