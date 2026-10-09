from abc import ABC, abstractmethod
from shared.domain.base_domain_event import BaseDomainEvent

class IEventPublisherPort(ABC):
    @abstractmethod
    async def publish(self, stream: str, payload: dict) -> None:
        pass
