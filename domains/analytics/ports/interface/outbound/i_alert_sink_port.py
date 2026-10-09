"""
File Overview: Outbound port interface for dispatching market and sentiment alerts to external sinks.

All Functions/Classes:
- i_alert_sink: Interface for alert delivery. Take alert payload and send to external integrations.
- send_alert: Dispatch alert to target sink. Take alert_dto and send to Discord/Email/Slack.

Endpoints/APIs: None

Database Tables: None
"""
from abc import ABC, abstractmethod

from domains.analytics.application.dto.alert_dto import AlertDTO

class IAlertSinkPort(ABC):
    @abstractmethod
    async def send_alert(self, payload: AlertDTO) -> None:
        pass
