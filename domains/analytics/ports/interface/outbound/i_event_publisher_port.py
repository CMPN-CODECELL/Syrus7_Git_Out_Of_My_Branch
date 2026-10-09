"""
File Overview: Outbound port interface for publishing events to the stream bus.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any

class IEventPublisherPort(ABC):
    @abstractmethod
    async def publish(self, stream: str, payload: Dict[str, Any]) -> None:
        """Publish a message to a specific stream."""
        pass
