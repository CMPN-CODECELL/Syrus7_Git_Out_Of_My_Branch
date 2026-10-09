"""
File Overview: Outbound adapter for publishing domain events to Redis Streams. Used by Celery workers.

All Functions/Classes:
- redis_event_bus_adapter: Sync event publisher for Celery tasks. Take payload and send to Redis Streams.
- publish: Map topic and dispatch event. Take topic/payload and send to mapped Stream.
- publish_to_stream: Generic stream publisher. Take stream/payload and send to Redis via XADD.

Endpoints/APIs: None

Database Tables: Redis (Streams: HEADLINE_FETCHED, PRICE_TRIGGER)
"""
import json
import logging
import redis.asyncio as redis
from shared.constants import Streams
from domains.ingestion.ports.interface.outbound.i_event_publisher_port import IEventPublisherPort

logger = logging.getLogger(__name__)

# Stream name mapping: event_type → Redis Stream
_EVENT_STREAM_MAP = {
    "ingestion.mkt": Streams.PRICE_TRIGGER,
}

_RETRY_FIELD = "__retry_count"

class RedisEventBusAdapter(IEventPublisherPort):
    """Publishes domain events to Redis Streams (async)."""

    def __init__(self, redis_client: redis.Redis):
        self._redis = redis_client

    async def publish(self, stream_alias_or_name: str, payload: dict) -> None:
        # Check alias map first, then use name directly
        stream = _EVENT_STREAM_MAP.get(stream_alias_or_name, stream_alias_or_name)
        
        fields = {
            "payload": json.dumps(payload, default=str),
            _RETRY_FIELD: "0",
        }
        try:
            msg_id = await self._redis.xadd(stream, fields, maxlen=10000, approximate=True)
            logger.info("Published to %s (msg_id=%s)", stream, msg_id)
        except Exception as exc:
            logger.error("Failed to publish to %s: %s", stream, exc)

    async def publish_to_stream(self, stream: str, payload: dict) -> None:
        """Publish directly to a named stream."""
        await self.publish(stream, payload)
