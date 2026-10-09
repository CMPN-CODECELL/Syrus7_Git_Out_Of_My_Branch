"""
File Overview: Outbound adapter for content deduplication using Redis. Ensures articles are processed only once.

All Functions/Classes:
- redis_dedup_adapter: Implementation of deduplication store. Take article IDs and send exists/set commands to Redis.
- is_seen: Check for existing entry. Take article_id and send boolean.
- mark_seen: Store seen ID with TTL. Take article_id and send to Redis.

Endpoints/APIs: None

Database Tables: Redis (Deduplication KV)
"""
import redis.asyncio as redis
from domains.ingestion.ports.interface.outbound.i_dedup_store_port import IDedupStorePort

class RedisDedupAdapter(IDedupStorePort):
    def __init__(self, redis_url: str):
        self.r = redis.from_url(redis_url)
    
    async def is_seen(self, article_id: str) -> bool:
        return await self.r.exists(article_id) == 1
        
    async def mark_seen(self, article_id: str) -> None:
        await self.r.set(article_id, "1", ex=86400) # 24h
