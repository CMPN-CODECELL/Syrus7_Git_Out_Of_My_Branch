"""
File Overview: Outbound adapter for alert dispatch via HTTP webhooks.
Implements i_alert_sink port interface. Supports concurrency limiting.

All Functions/Classes:
- webhook_adapter: Implementation of alert sink. Data: alert signals -> external HTTP targets.
- send_alert: Deliver alert payload. Data: alert_dto -> async POST request.

Endpoints/APIs: External Webhook POST targets.

Database Tables: None
"""
import logging
import asyncio
from typing import Optional

import aiohttp

from domains.analytics.ports.interface.outbound.i_alert_sink_port import IAlertSinkPort
from domains.analytics.application.dto.alert_dto import AlertDTO

logger = logging.getLogger(__name__)


class WebhookAdapter(IAlertSinkPort):
    """Concrete webhook adapter implementing the IAlertSinkPort port."""

    def __init__(self, url: str = None):
        self._url = url
        self._semaphore = asyncio.Semaphore(50)
        self._timeout = aiohttp.ClientTimeout(total=10)

    async def send_alert(self, payload: AlertDTO) -> None:
        if not self._url:
            logger.warning("Webhook URL not configured, alert dropped: %s", payload)
            return

        async with self._semaphore:
            try:
                async with aiohttp.ClientSession(timeout=self._timeout) as session:
                    async with session.post(
                        self._url,
                        json=payload.model_dump() if hasattr(payload, 'model_dump') else {},
                        headers={"Content-Type": "application/json"},
                    ) as resp:
                        if resp.status >= 400:
                            logger.error(
                                "Webhook POST failed (status=%d): %s",
                                resp.status,
                                await resp.text(),
                            )
                        else:
                            logger.info("Alert dispatched to webhook (status=%d)", resp.status)
            except asyncio.TimeoutError:
                logger.error("Webhook POST timed out: %s", self._url)
            except Exception as exc:
                logger.error("Webhook POST error: %s", exc)
