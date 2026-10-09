"""
File Overview: Data Transfer Object (DTO) for granular sentiment scores.

All Functions/Classes:
- sentiment_dto (class): Pydantic model for model output. Data: polarity/label -> validated DTO.

Endpoints/APIs:
- None.

Database Tables:
- None.
"""
from datetime import datetime

from shared.application.dto.base_dto import base_dto
from shared.constants import SentimentLabel

class SentimentDTO(base_dto):
    symbol: str
    polarity: float
    label: SentimentLabel
    confidence: float
    scored_at: datetime
