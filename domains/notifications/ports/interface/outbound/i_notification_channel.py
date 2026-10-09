from abc import ABC, abstractmethod
from domains.notifications.domain.entities import NotificationEvent, AlertRule


class INotificationChannelAdapterPort(ABC):
    """Outbound port for delivery channel adapters (WebSocket, Webhook, Email)."""

    @abstractmethod
    async def dispatch(self, event: NotificationEvent, rule: AlertRule) -> bool:
        """Dispatch notification event payload through delivery channel.
        Must return True on success, False/raise NotificationDeliveryError on failure.
        """
        pass
