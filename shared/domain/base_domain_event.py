"""
File Overview: Base class for domain events, providing shared metadata like IDs and timestamps.

All Functions/Classes:
- base_domain_event (class): Dataclass for event metadata. Data: Payload -> Versioned Event instance.

Endpoints/APIs:
- None.

Database Tables:
- None.
"""
import uuid

from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Dict, Any

@dataclass
class BaseDomainEvent:
    event_type: str = field(init=False)
    payload: Dict[str, Any]
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self):
        self.event_type = self.__class__.__name__
