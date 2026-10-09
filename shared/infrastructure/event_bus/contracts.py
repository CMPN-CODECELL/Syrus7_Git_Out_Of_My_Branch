"""
File Overview: Versioned domain event schemas and dataclasses for cross-domain communication.

All Functions/Classes:
- VersionedEvent (base class): Shared schema fields.
- PriceUpdatedV1, OptionsUpdatedV1, PriceTriggerV1, AnalysisRefreshRequestedV1: Specific event payload schemas. Data: Domain Events -> Serialized JSON.

Endpoints/APIs:
- None.

Database Tables:
- None.
"""
from dataclasses import asdict, dataclass, field

from datetime import datetime, timezone
from typing import Any, Literal


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class VersionedEvent:
    """Base schema fields shared by all domain event payloads."""

    event_type: str = field(init=False)
    schema_version: Literal["v1"] = "v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PriceUpdatedV1(VersionedEvent):
    symbol: str = ""
    last_price: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    volume: int = 0
    previous_close: float = 0.0
    change_percent: float = 0.0
    market_status: str = ""
    last_updated: str = ""
    fetched_at: str = field(default_factory=_utc_now_iso)

    def __post_init__(self) -> None:
        self.event_type = "market.price_updated"


@dataclass(slots=True)
class OptionsUpdatedV1(VersionedEvent):
    symbol: str = ""
    spot_price: float = 0.0
    expiry_dates: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    fetched_at: str = field(default_factory=_utc_now_iso)

    def __post_init__(self) -> None:
        self.event_type = "market.options_updated"


@dataclass(slots=True)
class PriceTriggerV1(VersionedEvent):
    symbol: str = ""
    trigger_type: str = ""
    current_price: float = 0.0
    previous_price: float = 0.0
    change_percent: float = 0.0
    description: str = ""
    triggered_at: str = field(default_factory=_utc_now_iso)

    def __post_init__(self) -> None:
        self.event_type = "market.price_trigger"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PriceTriggerV1":
        return cls(
            schema_version="v1",
            symbol=str(payload.get("symbol", "")),
            trigger_type=str(payload.get("trigger_type", "")),
            current_price=float(payload.get("current_price", 0.0)),
            previous_price=float(payload.get("previous_price", 0.0)),
            change_percent=float(payload.get("change_percent", 0.0)),
            description=str(payload.get("description", "")),
            triggered_at=str(payload.get("triggered_at", _utc_now_iso())),
        )


@dataclass(slots=True)
class AnalysisRefreshRequestedV1(VersionedEvent):
    symbol: str = ""
    reason: str = "stale_or_partial_read_model"
    requested_at: str = field(default_factory=_utc_now_iso)

    def __post_init__(self) -> None:
        self.event_type = "analysis.refresh_requested"


# Backward-compatible aliases (existing callers import these names).
PriceUpdatedEvent = PriceUpdatedV1
OptionsUpdatedEvent = OptionsUpdatedV1
PriceTriggerEvent = PriceTriggerV1
AnalysisRefreshRequestedEvent = AnalysisRefreshRequestedV1


__all__ = [
    "VersionedEvent",
    "PriceUpdatedV1",
    "OptionsUpdatedV1",
    "PriceTriggerV1",
    "AnalysisRefreshRequestedV1",
    "PriceUpdatedEvent",
    "OptionsUpdatedEvent",
    "PriceTriggerEvent",
    "AnalysisRefreshRequestedEvent",
]
