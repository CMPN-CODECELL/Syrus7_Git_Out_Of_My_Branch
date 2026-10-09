"""
File Overview: Domain events for the Analytics domain.
"""
from shared.domain.base_domain_event import BaseDomainEvent

class AnomalyDetectedEvent(BaseDomainEvent):
    pass

class PredictionReadyEvent(BaseDomainEvent):
    pass

class SignalFiredEvent(BaseDomainEvent):
    pass
