import pytest
import json
import uuid
from unittest.mock import AsyncMock, patch

from domains.notifications.domain.entities import AlertRule
from domains.notifications.domain.value_objects import ConditionType, DeliveryChannel
from domains.notifications.application.evaluate_alerts_service import EvaluateAlertsService
from domains.notifications.infrastructure.channels.websocket_channel import WebSocketNotificationChannelAdapter
from domains.notifications.infrastructure.channels.webhook_channel import WebhookNotificationChannelAdapter
from domains.notifications.infrastructure.subscribers.notification_subscriber import NotificationStreamSubscriber

@pytest.mark.asyncio
async def test_end_to_end_notification_pipeline():
    rule_id = uuid.uuid4()
    # 1. Setup real AlertRule
    rule = AlertRule(
        id=rule_id,
        symbol="NIFTY",
        condition_type=ConditionType.ABOVE_PRICE,
        threshold=24000.0,
        cooldown_seconds=300,
        channels=[DeliveryChannel.WEBSOCKET, DeliveryChannel.WEBHOOK],
        is_active=True,
        webhook_url="https://webhook.site/test"
    )

    # 2. Setup mock repository returning our real rule
    mock_repo = AsyncMock()
    mock_repo.get_active_rules_by_symbol.return_value = [rule]
    mock_repo.update_last_triggered = AsyncMock()
    mock_repo.log_notification_event = AsyncMock()

    # 3. Setup real Channel Adapters
    mock_redis = AsyncMock()
    mock_redis.publish = AsyncMock()
    ws_channel = WebSocketNotificationChannelAdapter(mock_redis)
    webhook_channel = WebhookNotificationChannelAdapter(timeout_seconds=5.0)

    # 4. Instantiate real Application Service
    evaluate_service = EvaluateAlertsService(
        repository=mock_repo,
        channels=[ws_channel, webhook_channel]
    )

    # 5. Instantiate Subscriber Daemon with evaluate_service overridden
    subscriber = NotificationStreamSubscriber(
        redis_client=mock_redis,
        repository=mock_repo
    )
    subscriber.evaluator = evaluate_service

    # 6. Simulate incoming stream payload (market tick above threshold)
    tick_payload = {
        "symbol": "NIFTY",
        "last_price": 24500.00,
        "timestamp": "2026-08-07T12:00:00Z"
    }

    event_payload = {
        b"data": json.dumps(tick_payload).encode("utf-8")
    }

    mock_resp = AsyncMock()
    mock_resp.is_success = True
    mock_resp.status_code = 200

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_http_post:
        mock_http_post.return_value = mock_resp

        # Execute consumer processing logic
        await subscriber.process_event(event_payload)

        # 7. Verification: Repository rule status was updated (update_last_triggered recorded)
        assert mock_repo.update_last_triggered.called
        assert mock_repo.update_last_triggered.call_args[0][0] == rule_id

        assert mock_repo.log_notification_event.called
        logged_event = mock_repo.log_notification_event.call_args[0][0]
        assert logged_event.rule_id == rule_id
        assert logged_event.triggered_value == 24500.0

        # 8. Verification: WebSocket message published to Redis channel
        assert mock_redis.publish.called
        pub_args = mock_redis.publish.call_args[0]
        assert pub_args[0] == "alerts.dispatched.NIFTY"
        published_payload = pub_args[1]
        assert published_payload["symbol"] == "NIFTY"
        assert published_payload["triggered_value"] == 24500.0

        # 9. Verification: Webhook HTTP POST delivered to endpoint
        assert mock_http_post.called
        post_kwargs = mock_http_post.call_args[1]
        assert "content" in post_kwargs
        sent_body = json.loads(post_kwargs["content"].decode("utf-8"))
        assert sent_body["rule_id"] == str(rule_id)
        assert sent_body["value"] == 24500.0
