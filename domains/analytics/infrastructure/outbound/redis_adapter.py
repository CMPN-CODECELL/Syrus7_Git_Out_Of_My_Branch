"""
File Overview: Outbound adapter for Redis caching and read-model state management.
Implements the i_cache port interface for the analytics domain.

All Functions/Classes:
- redis_adapter: Implementation of cache interface. Data: key-value pairs -> Redis storage.
- get: Retrieve cached value. Data: key -> Redis GET -> string.
- set: Store value with TTL. Data: key/val/ttl -> Redis SETEX.
- delete: Remove cached entry. Data: key -> Redis DEL.

Endpoints/APIs: None

Database Tables: None (Redis KV store)
"""
import json
import logging
import asyncio
from typing import Optional, Dict, Any

from domains.analytics.ports.interface.outbound.i_cache_port import ICachePort
from domains.analytics.ports.interface.outbound.i_event_publisher_port import IEventPublisherPort
from shared.infrastructure.event_bus.streams import DurableEventStream

logger = logging.getLogger(__name__)


class RedisAdapter(ICachePort, IEventPublisherPort):
    """Concrete Redis implementation for caching and event publishing."""

    def __init__(self, redis_client=None):
        self._client = redis_client
        self._stream_bus = None

    async def _get_client(self):
        if self._client is not None:
            return self._client
        from shared.infrastructure.redis_client import get_redis_client
        self._client = await get_redis_client()
        return self._client

    async def _get_stream_bus(self):
        if self._stream_bus is not None:
            return self._stream_bus
        client = await self._get_client()
        self._stream_bus = DurableEventStream(client)
        return self._stream_bus

    async def get(self, key: str) -> str:
        try:
            client = await self._get_client()
            val = await client.get(key)
            return val if val is not None else ""
        except Exception as exc:
            logger.error("Redis GET failed for key=%s: %s", key, exc)
            return ""

    async def set(self, key: str, val: str, ttl: int) -> None:
        try:
            client = await self._get_client()
            await client.set(key, val, ex=ttl)
        except Exception as exc:
            logger.error("Redis SET failed for key=%s: %s", key, exc)

    async def delete(self, key: str) -> None:
        try:
            client = await self._get_client()
            await client.delete(key)
        except Exception as exc:
            logger.error("Redis DELETE failed for key=%s: %s", key, exc)

    async def publish(self, stream: str, payload: Dict[str, Any]) -> None:
        """Publish message to Redis Stream."""
        try:
            bus = await self._get_stream_bus()
            await bus.publish(stream, payload)
        except Exception as exc:
            logger.error("Redis PUBLISH failed for stream=%s: %s", stream, exc)

    async def zadd(self, key: str, score: float, member: str) -> None:
        try:
            client = await self._get_client()
            await client.zadd(key, {member: score})
        except Exception as exc:
            logger.error("Redis ZADD failed for key=%s: %s", key, exc)

    async def zremrangebyrank(self, key: str, start: int, stop: int) -> None:
        try:
            client = await self._get_client()
            await client.zremrangebyrank(key, start, stop)
        except Exception as exc:
            logger.error("Redis ZREMRANGEBYRANK failed for key=%s: %s", key, exc)

    async def publish_pubsub(self, channel: str, message: str) -> None:
        try:
            client = await self._get_client()
            await client.publish(channel, message)
        except Exception as exc:
            logger.error("Redis publish_pubsub failed for channel=%s: %s", channel, exc)

