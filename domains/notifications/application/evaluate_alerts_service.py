import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import uuid

from domains.notifications.domain.entities import AlertRule, NotificationEvent
from domains.notifications.domain.value_objects import AlertStatus
from domains.notifications.domain.services.rule_matcher import RuleMatcherDomainService
from domains.notifications.ports.interface.inbound.i_evaluate_alerts import (
    IEvaluateAlertsUseCasePort,
)
from domains.notifications.ports.interface.outbound.i_alert_repository import (
    IAlertRuleRepositoryPort,
)
from domains.notifications.ports.interface.outbound.i_notification_channel import (
    INotificationChannelAdapterPort,
)

logger = logging.getLogger(__name__)


class EvaluateAlertsService(IEvaluateAlertsUseCasePort):
    """Application service for evaluating stream tick events against active alert rules."""

    def __init__(
        self,
        repository: IAlertRuleRepositoryPort,
        channels: Optional[List[INotificationChannelAdapterPort]] = None,
    ):
        self._repo = repository
        self._channels = channels or []

    async def evaluate_tick_event(
        self, symbol: str, tick_payload: Dict[str, Any]
    ) -> List[NotificationEvent]:
        active_rules = await self._repo.get_active_rules_by_symbol(symbol)
        if not active_rules:
            return []

        now = datetime.now(timezone.utc)
        triggered_events: List[NotificationEvent] = []

        for rule in active_rules:
            # Check cooldown period
            if rule.is_in_cooldown(now):
                continue

            is_matched, actual_val, msg = RuleMatcherDomainService.match(rule, tick_payload)
            if not is_matched or actual_val is None or msg is None:
                continue

            event = NotificationEvent(
                id=uuid.uuid4(),
                rule_id=rule.id,
                symbol=rule.symbol.upper(),
                condition_type=rule.condition_type,
                triggered_value=actual_val,
                threshold=rule.threshold,
                message=msg,
                channels=rule.channels,
                timestamp=now,
                status=AlertStatus.PENDING,
            )

            # Dispatch via channel adapters
            dispatch_success = True
            error_details = []

            for channel in self._channels:
                try:
                    ok = await channel.dispatch(event, rule)
                    if not ok:
                        dispatch_success = False
                        error_details.append(f"Channel {channel.__class__.__name__} failed")
                except Exception as ex:
                    dispatch_success = False
                    error_details.append(str(ex))

            if dispatch_success:
                event.status = AlertStatus.DELIVERED
            else:
                event.status = AlertStatus.FAILED
                event.error_message = "; ".join(error_details)

            # Update last_triggered timestamp on rule
            await self._repo.update_last_triggered(rule.id, now)

            # Log execution event to DB
            await self._repo.log_notification_event(event)
            triggered_events.append(event)
            logger.info(f"Triggered notification alert {event.id} for rule {rule.id} on {symbol}")

        return triggered_events
