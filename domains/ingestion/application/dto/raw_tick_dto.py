"""
File Overview: Data Transfer Object (DTO) for raw market ticks fetched from exchange feeders.

All Functions/Classes:
- raw_tick_dto: Normalized representation of market price data. Take raw API response and send to analytics ingestion services.

Endpoints/APIs: None

Database Tables: None
"""
from datetime import datetime
from shared.application.dto.base_dto import BaseDTO

class RawTickDTO(BaseDTO):
    symbol: str
    expiry: str
    strike: float
    option_type: str
    oi: int
    volume: int
    ltp: float
    iv: float = 0.0
    bid: float = 0.0
    bid_qty: int = 0
    ask: float = 0.0
    ask_qty: int = 0
    underlying_price: float = 0.0
    timestamp: datetime
