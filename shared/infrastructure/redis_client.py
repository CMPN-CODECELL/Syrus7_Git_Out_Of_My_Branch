"""
File Overview: Shared Redis client management for both asynchronous and synchronous contexts.

All Functions/Classes:
- get_redis_client: Singleton getter for async aioredis client. Data: App Config -> Async Redis.
- close_redis_client: Gracefully shuts down async client. Data: Active Client -> Closed.
- get_redis_client_sync: Returns synchronous Redis client. Data: App Config -> Sync Redis.

Endpoints/APIs: None

Database Tables: None
"""
import logging
from typing import Optional

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# ── Module-level singleton ──────────────────────────────────────
_redis_client: Optional[aioredis.Redis] = None
_redis_healthy: bool = False
_redis_sync_client = None


async def get_redis_client() -> aioredis.Redis:
    """
    Return the shared async Redis client.
    Creates the connection pool on first call; reuses it thereafter.
    Re-pings on access if the last connection attempt failed.
    """
    global _redis_client, _redis_healthy

    if _redis_client is not None and _redis_healthy:
        return _redis_client

    from app.config import get_settings
    cfg = get_settings()

    # Create client if needed (or recreate after a close)
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            cfg.RedisUrl,
            decode_responses=True,
            max_connections=50,
            socket_connect_timeout=5,
            socket_keepalive=True,
            retry_on_timeout=True,
        )

    try:
        await _redis_client.ping()
        _redis_healthy = True
        logger.info("Redis connected  (%s)", cfg.RedisUrl)
    except (aioredis.ConnectionError, aioredis.RedisError, OSError) as exc:
        _redis_healthy = False
        logger.error("Redis connection failed: %s  — continuing without Redis", exc)

    return _redis_client


async def close_redis_client() -> None:
    """Graceful shutdown — call from FastAPI lifespan shutdown."""
    global _redis_client, _redis_healthy

    if _redis_client is not None:
        try:
            await _redis_client.aclose()
            logger.info("Redis client closed")
        except Exception as exc:
            logger.error("Error closing Redis client: %s", exc)
        finally:
            _redis_client = None
            _redis_healthy = False


# Backward-compatible alias
CloseRedisClient = close_redis_client


def get_redis_client_sync():
    """
    Returns a sync Redis client connection.
    """
    global _redis_sync_client
    if _redis_sync_client is not None:
        return _redis_sync_client

    from app.config import get_settings
    cfg = get_settings()
    import redis
    _redis_sync_client = redis.Redis.from_url(cfg.RedisUrl, decode_responses=True)
    return _redis_sync_client