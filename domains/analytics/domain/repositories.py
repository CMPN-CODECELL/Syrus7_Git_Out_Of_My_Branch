"""
File Overview: Repository interfaces (outbound ports) for the Analytics domain.
"""
from abc import ABC, abstractmethod
from typing import List
from domains.analytics.domain.entities import SentimentScoreEntity
from shared.domain.base_domain_event import BaseDomainEvent

class ISentimentRepository(ABC):
    @abstractmethod
    async def save_score(self, score: SentimentScoreEntity) -> None:
        pass

    @abstractmethod
    async def get_last_n(self, symbol: str, n: int) -> List[SentimentScoreEntity]:
        pass

class IEventStoreRepository(ABC):
    @abstractmethod
    async def save_event(self, event: BaseDomainEvent) -> None:
        pass

    @abstractmethod
    async def get_events(self, symbol: str, limit: int) -> List[BaseDomainEvent]:
        pass

class IModelStoreRepository(ABC):
    @abstractmethod
    def save_model(self, symbol: str, path: str) -> None:
        pass

    @abstractmethod
    def load_model(self, symbol: str) -> str:
        pass
