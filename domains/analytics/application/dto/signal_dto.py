"""
File Overview: Data Transfer Object (DTO) for technical trading signals.

All Functions/Classes:
- signal_dto (class): Pydantic model for signal event data. Data: SMA/Crossover info -> validated DTO.

Endpoints/APIs:
- None.

Database Tables:
- None.
"""
from datetime import datetime

from shared.application.dto.base_dto import base_dto

class SignalDTO(base_dto):
    symbol: str
    signal_type: str
    sma: float
    triggered_at: datetime
