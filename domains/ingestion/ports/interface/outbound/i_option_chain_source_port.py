from abc import ABC, abstractmethod
from typing import List
from domains.ingestion.application.dto.raw_tick_dto import RawTickDTO

class IOptionChainSourcePort(ABC):
    @abstractmethod
    async def fetch_option_chain(self, symbol: str) -> List[RawTickDTO]:
        pass
