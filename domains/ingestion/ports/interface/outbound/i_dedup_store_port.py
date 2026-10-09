from abc import ABC, abstractmethod

class IDedupStorePort(ABC):
    @abstractmethod
    async def is_seen(self, article_id: str) -> bool:
        pass
    @abstractmethod
    async def mark_seen(self, article_id: str) -> None:
        pass
