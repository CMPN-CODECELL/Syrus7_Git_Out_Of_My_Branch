"""
File Overview: Domain entities and aggregates for the Analytics context.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional
from domains.ingestion.application.dto.raw_tick_dto import RawTickDTO
from domains.analytics.domain.events import AnomalyDetectedEvent, SignalFiredEvent

@dataclass
class DerivativeSnapshotEntity:
    symbol: str
    expiry: str
    pcr: float
    iv_surface: Dict[str, float]
    anomalies: List[str]
    computed_at: datetime

@dataclass
class PredictionEntity:
    symbol: str
    bullish_prob: float
    bearish_prob: float
    model_version: str
    predicted_at: datetime

@dataclass
class SignalEntity:
    symbol: str
    signal_type: str
    sma_value: float
    triggered_at: datetime

class OptionsChainAggregate:
    OI_SURGE_THRESHOLD = 3.0
    VOL_SWEEP_THRESHOLD = 5.0

    def __init__(self):
        self.ticks: List[RawTickDTO] = []
        
    def add_tick_batch(self, ticks: List[RawTickDTO]) -> List[AnomalyDetectedEvent]:
        self.ticks.extend(ticks)
        return self.detect_anomalies()
        
    def detect_anomalies(self) -> List[AnomalyDetectedEvent]:
        anomalies = []
        for tick in self.ticks:
            pass # TODO: EWM logic
        return anomalies

