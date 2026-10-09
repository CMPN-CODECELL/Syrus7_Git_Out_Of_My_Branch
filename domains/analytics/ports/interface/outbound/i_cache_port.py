"""
File Overview: Outbound port interface for key-value cache layer (Redis). Used for snapshots and session state.

All Functions/Classes:
- i_cache: Interface for cache operations. Take keys/values and send to transient storage.
- get: Retrieve string value. Take key and send cached string.
- set: Store value with TTL. Take key/val/ttl and send to cache.
- delete: Remove entry. Take key and send deletion command.

Endpoints/APIs: None

Database Tables: None
"""
from abc import ABC, abstractmethod


class ICachePort(ABC):
    @abstractmethod
    async def get(self, key: str) -> str:
        pass
    @abstractmethod
    async def set(self, key: str, val: str, ttl: int) -> None:
        pass
    @abstractmethod
    async def delete(self, key: str) -> None:
        pass
    @abstractmethod
    async def zadd(self, key: str, score: float, member: str) -> None:
        pass
    @abstractmethod
    async def zremrangebyrank(self, key: str, start: int, stop: int) -> None:
        pass
    @abstractmethod
    async def publish_pubsub(self, channel: str, message: str) -> None:
        pass

