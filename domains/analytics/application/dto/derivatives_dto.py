"""
File Overview: Data Transfer Object (DTO) for derivatives analytics.

All Functions/Classes:
- derivatives_dto: Pydantic model for options metrics. Take PCR/IV stats and send validated DTO.

Endpoints/APIs: None

Database Tables: None
"""
from datetime import datetime

from typing import Dict, List
from shared.application.dto.base_dto import base_dto

class DerivativesDTO(base_dto):
    symbol: str
    pcr: float
    iv_surface: Dict[str, float]
    anomalies: List[str]
    computed_at: datetime
