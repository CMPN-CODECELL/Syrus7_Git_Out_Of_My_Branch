import logging
import hmac
import hashlib
import json
import httpx

from domains.notifications.domain.entities import NotificationEvent, AlertRule
from domains.notifications.domain.exceptions import NotificationDeliveryError
from domains.notifications.ports.interface.outbound.i_notification_channel import (
    INotificationChannelAdapterPort,
)

logger = logging.getLogger(__name__)


class WebhookNotificationChannelAdapter(INotificationChannelAdapterPort):
    """Outbound adapter delivering alert payloads via HTTP POST to user webhooks."""

    def __init__(self, timeout_seconds: float = 5.0):
        self._timeout = timeout_seconds

    async def dispatch(self, event: NotificationEvent, rule: AlertRule) -> bool:
        if not rule.webhook_url:
            logger.warning(f"Webhook channel invoked for rule {rule.id} but webhook_url is missing")
            return False

        payload = {
            "event_id": str(event.id),
            "rule_id": str(event.rule_id),
            "symbol": event.symbol,
            "condition": event.condition_type.value,
            "value": event.triggered_value,
            "threshold": event.threshold,
            "message": event.message,
            "timestamp": event.timestamp.isoformat(),
        }

        body_bytes = json.dumps(payload).encode("utf-8")
        signature = hmac.new(
            str(rule.id).encode("utf-8"), body_bytes, hashlib.sha256
        ).hexdigest()

        headers = {
            "Content-Type": "application/json",
            "X-AlphaStreams-Signature": signature,
            "User-Agent": "AlphaStreams-Alerts/2.0",
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(rule.webhook_url, content=body_bytes, headers=headers)
                if resp.is_success:
                    logger.info(f"Webhook notification delivered for event {event.id} to {rule.webhook_url}")
                    return True
                else:
                    logger.error(f"Webhook POST failed status={resp.status_code} for {rule.webhook_url}")
                    return False
        except Exception as ex:
            logger.error(f"Webhook HTTP error for {rule.webhook_url}: {ex}")
            return False
