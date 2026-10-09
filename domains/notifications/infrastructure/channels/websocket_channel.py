import logging
from typing import Optional
import json

from domains.notifications.domain.entities import NotificationEvent, AlertRule
from domains.notifications.ports.interface.outbound.i_notification_channel import (
    INotificationChannelAdapterPort,
)
from shared.constants import Channels
from shared.infrastructure.event_bus import EventBus

logger = logging.getLogger(__name__)


class WebSocketNotificationChannelAdapter(INotificationChannelAdapterPort):
    """Outbound adapter dispatching notification events over Redis Pub/Sub to WebSockets."""

    def __init__(self, event_bus: Optional[EventBus] = None):
        self._event_bus = event_bus

    async def _get_bus(self) -> EventBus:
        if self._event_bus is not None:
            return self._event_bus
        return EventBus()

    async def dispatch(self, event: NotificationEvent, rule: AlertRule) -> bool:
        bus = await self._get_bus()
        channel_name = Channels.ALERT_DISPATCHED.format(symbol=event.symbol.upper())

        payload = {
            "type": "ALERT_NOTIFICATION",
            "id": str(event.id),
            "rule_id": str(event.rule_id),
            "symbol": event.symbol,
            "condition_type": event.condition_type.value,
            "triggered_value": event.triggered_value,
            "threshold": event.threshold,
            "message": event.message,
            "timestamp": event.timestamp.isoformat(),
        }

        try:
            receivers = await bus.publish(channel_name, payload)
            logger.info(f"Broadcast alert {event.id} on Redis channel {channel_name} ({receivers} listeners)")
            return True
        except Exception as ex:
            logger.error(f"Failed to publish WebSocket alert on {channel_name}: {ex}")
            return False
