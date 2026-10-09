import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.contracts.orders import OrderPayload


class TriggerCondition(BaseModel):
    """When a standing instruction fires. Price levels are paise and evaluated on 021 prices;
    indicator conditions are evaluated on closed analysis-feed bars."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["CROSS_BELOW", "CROSS_ABOVE", "DAY_DROP_PCT", "INDICATOR_BELOW", "INDICATOR_ABOVE"]
    token: Optional[int] = None
    exchange: Optional[str] = None
    level_paise: Optional[int] = Field(None, gt=0)
    pct: Optional[float] = Field(None, gt=0, lt=100)
    indicator: Optional[Literal["RSI14_D"]] = None
    indicator_value: Optional[float] = None
    scope: Literal["INSTRUMENT", "ALL_HOLDINGS"] = "INSTRUMENT"
    fire_if_already_past: bool = False

    @model_validator(mode="after")
    def _check(self) -> "TriggerCondition":
        if self.kind in ("CROSS_BELOW", "CROSS_ABOVE") and (self.level_paise is None or self.token is None):
            raise ValueError("price crossing needs token and level_paise")
        if self.kind == "DAY_DROP_PCT" and self.pct is None:
            raise ValueError("DAY_DROP_PCT needs pct")
        if self.kind.startswith("INDICATOR") and (self.indicator is None or self.indicator_value is None):
            raise ValueError("indicator conditions need indicator and indicator_value")
        return self


class StandingInstruction(BaseModel):
    """Persisted instruction. The attached order (if any) was approved at creation and is
    re-validated against limits and live 021 prices at fire time."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    user_id: str
    condition: TriggerCondition
    action: Literal["ALERT", "ORDER"]
    order: Optional[OrderPayload] = None
    order_hash: Optional[str] = None
    created_at: datetime
    expires_at: datetime
    state: Literal["ACTIVE", "PAUSED", "FIRING", "DONE", "FAILED", "CANCELLED", "EXPIRED"] = "ACTIVE"

    @model_validator(mode="after")
    def _check(self) -> "StandingInstruction":
        if self.action == "ORDER":
            if self.order is None or self.order_hash != self.order.payload_hash():
                raise ValueError("ORDER instructions need an order whose hash matches order_hash")
        elif self.order is not None:
            raise ValueError("ALERT instructions carry no order")
        return self
