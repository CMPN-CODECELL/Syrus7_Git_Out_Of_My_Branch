"""
File Overview: Inbound adapter for Celery task bridging. Implements news and tick processing ports.

All Functions/Classes:
- celery_consumer_adapter (class): Implementation of inbound ports. Data: Celery tasks -> domain aggregates/services.
- process: Dispatch incoming DTOs. Data: incoming payload -> internal logic.

Endpoints/APIs:
- None.

Database Tables:
- None.
"""
from domains.analytics.ports.interface.inbound.i_article_processor_port import IArticleProcessorPort
from domains.analytics.ports.interface.inbound.i_tick_processor_port import ITickProcessorPort
from typing import List
from domains.ingestion.application.dto.raw_tick_dto import RawTickDTO
from domains.ingestion.application.dto.raw_article_dto import RawArticleDTO

class CeleryConsumerAdapter(IArticleProcessorPort, ITickProcessorPort):
    def process(self, dto) -> None:
        raise NotImplementedError(" प्रोसेस() not implemented.")
