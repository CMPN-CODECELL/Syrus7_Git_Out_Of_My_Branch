"""
File Overview: Repository interfaces (outbound ports) for the Ingestion domain.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from domains.ingestion.application.dto.raw_tick_dto import RawTickDTO
from domains.ingestion.application.dto.raw_article_dto import RawArticleDTO

class IDedupRepository(ABC):
    @abstractmethod
    async def is_seen(self, article_id: str) -> bool:
        pass

    @abstractmethod
    async def mark_seen(self, article_id: str) -> None:
        pass

class INewsSourceRepository(ABC):
    @abstractmethod
    async def fetch_articles(self, symbol: str) -> List[RawArticleDTO]:
        pass

class IOptionChainSourceRepository(ABC):
    @abstractmethod
    async def fetch_option_chain(self, symbol: str) -> List[RawTickDTO]:
        pass

class IMarketPriceSourceRepository(ABC):
    @abstractmethod
    async def fetch_price(self, symbol: str) -> Optional[dict]:
        pass
