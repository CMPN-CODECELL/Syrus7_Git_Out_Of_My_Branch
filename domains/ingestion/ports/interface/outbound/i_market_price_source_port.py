from abc import ABC, abstractmethod
from typing import Optional

class IMarketPriceSourcePort(ABC):
    @abstractmethod
    async def fetch_price(self, symbol: str) -> Optional[dict]:
        pass
