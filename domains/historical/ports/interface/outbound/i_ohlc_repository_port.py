"""
File Overview: Outbound port interface for historical OHLC candle persistence.
"""
from abc import ABC, abstractmethod
from typing import List, Optional
from datetime import datetime

from domains.historical.domain.entities import CandleEntity


class IOhlcRepositoryPort(ABC):
    """Outbound repository port interface for OHLC hypertable operations."""

    @abstractmethod
    async def save_candles(self, candles: List[CandleEntity]) -> int:
        """Bulk insert OHLC candles into database."""
        pass

    @abstractmethod
    async def get_candles(
        self,
        symbol: str,
        timeframe: str = "1m",
        limit: int = 100,
        end_time: Optional[datetime] = None,
    ) -> List[CandleEntity]:
        """Query historical OHLC candles ordered by timestamp ascending."""
        pass
