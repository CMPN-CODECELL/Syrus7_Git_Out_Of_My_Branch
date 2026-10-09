"""
File Overview: Outbound adapter for TimescaleDB/Postgres persistence.
Implements i_event_store port interface.

All Functions/Classes:
- timescale_adapter: Unified store for domain events.
- save_event: Persist domain event. Data: base_domain_event -> SQL INSERT.
- get_events: Retrieve recent events. Data: symbol/limit -> list of base_domain_event.

Endpoints/APIs: None

Database Tables:
- domain_events (event log)
"""
import json
import logging
import asyncio
from typing import List, Optional

from domains.analytics.ports.interface.outbound.i_event_store_port import IEventStorePort
from shared.domain.base_domain_event import BaseDomainEvent

logger = logging.getLogger(__name__)


class TimescaleAdapter(IEventStorePort):
    """Concrete TimescaleDB adapter implementing event store port."""

    def __init__(self, url: str = None):
        self._url = url
        self._pool = None

    async def _get_pool(self):
        if self._pool is not None:
            return self._pool
        from shared.infrastructure.database import GetDatabasePool
        self._pool = await GetDatabasePool()
        return self._pool

    async def save_event(self, event: BaseDomainEvent) -> None:
        """Persist a domain event to the event log."""
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                # Assuming a table structure for events exists or using a generic log
                await conn.execute(
                    """INSERT INTO DomainEvents (EventId, EventType, Payload, OccurredAt)
                       VALUES ($1, $2, $3, $4)""",
                    event.event_id,
                    event.event_type,
                    json.dumps(event.payload, default=str),
                    event.occurred_at,
                )
        except Exception as exc:
            logger.error("Failed to save domain event %s: %s", event.event_type, exc)

    async def get_events(self, symbol: str, limit: int) -> List[BaseDomainEvent]:
        """Retrieve recent domain events for a symbol."""
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT EventId as event_id, EventType as event_type, Payload as payload, OccurredAt as occurred_at
                       FROM DomainEvents
                       WHERE Payload::jsonb->>'symbol' = $1
                       ORDER BY OccurredAt DESC LIMIT $2""",
                    symbol, limit,
                )
                return [
                    BaseDomainEvent(
                        payload=json.loads(r["payload"]),
                        event_id=r["event_id"],
                        occurred_at=r["occurred_at"],
                    )
                    for r in rows
                ]
        except Exception as exc:
            logger.error("Failed to query domain events for %s: %s", symbol, exc)
            return []
