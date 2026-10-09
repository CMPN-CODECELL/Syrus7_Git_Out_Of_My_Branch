from typing import List, Optional
import uuid
from fastapi import APIRouter, HTTPException, Depends, status

from domains.notifications.api.schemas import (
    CreateAlertRuleRequest,
    AlertRuleResponse,
)
from domains.notifications.domain.entities import AlertRule
from domains.notifications.domain.exceptions import AlertRuleNotFoundError
from domains.notifications.application.manage_alerts_service import ManageAlertRulesService
from domains.notifications.infrastructure.persistence.alert_repository import PostgresAlertRuleRepository

router = APIRouter(prefix="/v1/notifications", tags=["Notifications & Alerts"])


def get_manage_alerts_service() -> ManageAlertRulesService:
    repo = PostgresAlertRuleRepository()
    return ManageAlertRulesService(repository=repo)


@router.post("/alerts", response_model=AlertRuleResponse, status_code=status.HTTP_201_CREATED)
async def create_alert_rule(
    req: CreateAlertRuleRequest,
    service: ManageAlertRulesService = Depends(get_manage_alerts_service),
):
    """Create a new real-time market alert rule."""
    rule = AlertRule(
        id=uuid.uuid4(),
        symbol=req.symbol.upper(),
        condition_type=req.condition_type,
        threshold=req.threshold,
        channels=req.channels,
        cooldown_seconds=req.cooldown_seconds,
        webhook_url=req.webhook_url,
        email_destination=req.email_destination,
        is_active=True,
    )
    created = await service.create_rule(rule)
    return created


@router.get("/alerts", response_model=List[AlertRuleResponse])
async def list_alert_rules(
    symbol: Optional[str] = None,
    service: ManageAlertRulesService = Depends(get_manage_alerts_service),
):
    """List active user alert rules optionally filtered by symbol."""
    return await service.list_active_rules(symbol=symbol)


@router.get("/alerts/{rule_id}", response_model=AlertRuleResponse)
async def get_alert_rule(
    rule_id: uuid.UUID,
    service: ManageAlertRulesService = Depends(get_manage_alerts_service),
):
    """Get details of a specific alert rule."""
    try:
        return await service.get_rule(rule_id)
    except AlertRuleNotFoundError:
        raise HTTPException(status_code=404, detail=f"Alert rule {rule_id} not found")


@router.delete("/alerts/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert_rule(
    rule_id: uuid.UUID,
    service: ManageAlertRulesService = Depends(get_manage_alerts_service),
):
    """Delete an existing alert rule."""
    try:
        await service.delete_rule(rule_id)
    except AlertRuleNotFoundError:
        raise HTTPException(status_code=404, detail=f"Alert rule {rule_id} not found")
