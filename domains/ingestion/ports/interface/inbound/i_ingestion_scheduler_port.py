from abc import ABC, abstractmethod

class IIngestionSchedulerPort(ABC):
    @abstractmethod
    def trigger_news(self, symbol: str) -> None:
        pass
    @abstractmethod
    def trigger_ticks(self, symbol: str) -> None:
        pass
