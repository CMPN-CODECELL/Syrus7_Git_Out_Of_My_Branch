"""
File Overview: Data Transfer Object (DTO) for machine learning prediction outputs.

All Functions/Classes:
- prediction_dto: Pydantic model for inference results. Take probability/version and send validated DTO.

Endpoints/APIs: None

Database Tables: None
"""
from datetime import datetime

from shared.application.dto.base_dto import base_dto

class PredictionDTO(base_dto):
    symbol: str
    bullish_prob: float
    model_version: str
    predicted_at: datetime
