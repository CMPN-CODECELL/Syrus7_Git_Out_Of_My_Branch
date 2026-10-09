from abc import ABC, abstractmethod
from typing import List, Any, Dict

from domains.notifications.domain.entities import NotificationEvent


class IEvaluateAlertsUseCasePort(ABC):
    """Inbound port for processing market data tick/price events and evaluating rules."""

    @abstractmethod
    async def evaluate_tick_event(
        self, symbol: str, tick_payload: Dict[str, Any]
    ) -> List[NotificationEvent]:
        """Evaluate incoming tick stream event payload against active alert rules.
        Returns list of triggered notification events.
        """
        pass
