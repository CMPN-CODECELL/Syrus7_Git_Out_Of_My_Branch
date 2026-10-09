"""
File Overview: Inbound port interface for processing raw news articles. Defines the contract for news handling from ingestion.

All Functions/Classes:
- i_article_processor: Interface for news processing logic. Take raw articles and send to scoring/persistence.
- process: Orchestrate NLP scoring and persistence. Take raw_article_dto and send to domain services.

Endpoints/APIs: None

Database Tables: None
"""
from abc import ABC, abstractmethod

from domains.ingestion.application.dto.raw_article_dto import raw_article_dto

class IArticleProcessorPort(ABC):
    @abstractmethod
    def process(self, dto: raw_article_dto) -> None:
        pass
