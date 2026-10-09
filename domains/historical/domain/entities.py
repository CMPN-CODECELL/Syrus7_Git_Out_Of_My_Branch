"""
File Overview: Domain entities and value objects for Historical OHLC Bounded Context.
"""
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CandleEntity:
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    timeframe: str = "1m"
