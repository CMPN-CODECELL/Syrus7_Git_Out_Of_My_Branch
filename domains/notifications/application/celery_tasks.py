import logging
import asyncio
from typing import Dict, Any

logger = logging.getLogger(__name__)

# Lazy Celery import if Celery is running
try:
    from shared.celery_app import celery_app
except ImportError:
    celery_app = None


def _run_async(coro):
    """Utility to safely execute coroutine inside synchronous Celery worker execution context."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


if celery_app:
    @celery_app.task(name="notifications.dispatch_webhook_task", bind=True, max_retries=3)
    def dispatch_webhook_task(self, rule_id_str: str, event_payload: Dict[str, Any]):
        """Background Celery task for async HTTP Webhook dispatching."""
        from domains.notifications.domain.entities import AlertRule, NotificationEvent
        from domains.notifications.domain.value_objects import ConditionType, DeliveryChannel, AlertStatus
        from domains.notifications.infrastructure.channels.webhook_channel import WebhookNotificationChannelAdapter
        import uuid
        from datetime import datetime

        logger.info(f"Executing Celery async webhook task for rule {rule_id_str}")
        rule = AlertRule(
            id=uuid.UUID(rule_id_str),
            symbol=event_payload["symbol"],
            condition_type=ConditionType(event_payload["condition"]),
            threshold=float(event_payload["threshold"]),
            channels=[DeliveryChannel.WEBHOOK],
            webhook_url=event_payload.get("webhook_url"),
        )
        event = NotificationEvent(
            id=uuid.UUID(event_payload["event_id"]),
            rule_id=rule.id,
            symbol=rule.symbol,
            condition_type=rule.condition_type,
            triggered_value=float(event_payload["value"]),
            threshold=rule.threshold,
            message=event_payload["message"],
            channels=[DeliveryChannel.WEBHOOK],
            timestamp=datetime.fromisoformat(event_payload["timestamp"]),
        )

        adapter = WebhookNotificationChannelAdapter()
        success = _run_async(adapter.dispatch(event, rule))
        if not success:
            raise self.retry(exc=RuntimeError("Webhook dispatch failed"), countdown=5)
        return True
