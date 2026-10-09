"""
File Overview: Data Transfer Object (DTO) for raw news articles fetched from external APIs.

All Functions/Classes:
- raw_article_dto: Normalized representation of a news article. Take raw JSON from source and send to domain entity or event bus.

Endpoints/APIs: None

Database Tables: None
"""
from datetime import datetime
from shared.application.dto.base_dto import BaseDTO

class RawArticleDTO(BaseDTO):
    symbol: str
    headline: str
    body: str
    source: str
    published_at: datetime
    url: str
