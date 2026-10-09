"""
File Overview: Inbound port interface for processing market ticks and derivatives data. Entry point for real-time data ingestion.

All Functions/Classes:
- i_tick_processor: Interface for market data ingestion. Take ticks and send to derivatives processing.
- process: Batch process market data. Take list of raw_tick_dto and send to compute metrics.

Endpoints/APIs: None

Database Tables: None
"""
from abc import ABC, abstractmethod

from typing import List
from domains.ingestion.application.dto.raw_tick_dto import raw_tick_dto

class ITickProcessorPort(ABC):
    @abstractmethod
    def process(self, dto: List[raw_tick_dto]) -> None:
        pass
