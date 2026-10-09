"""
File Overview: Domain entities representing raw ingestion models.
"""
from dataclasses import dataclass
from datetime import datetime

@dataclass
class RawArticleEntity:
    id: str
    symbol: str
    headline: str
    body: str
    source: str
    published_at: datetime

@dataclass
class RawTickEntity:
    symbol: str
    expiry: str
    strike: float
    ce_oi: int
    pe_oi: int
    ce_vol: int
    pe_vol: int
    ltp: float
    timestamp: datetime
