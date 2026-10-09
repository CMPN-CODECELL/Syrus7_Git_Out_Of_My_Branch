"""
File Overview: Outbound port interface for persisting domain events within the analytics context.

All Functions/Classes:
- i_event_store: Interface for event persistence. Take domain events and send to durable store.
- save_event: Persist domain event. Take base_domain_event and send to TimescaleDB/EventStoreDB.
- get_events: Retrieve recent history. Take symbol/limit and send list of domain events.

Endpoints/APIs: None

Database Tables: None
"""
from typing import List
from shared.domain.base_domain_event import BaseDomainEvent
from domains.analytics.domain.repositories import IEventStoreRepository

class IEventStorePort(IEventStoreRepository):
    pass

