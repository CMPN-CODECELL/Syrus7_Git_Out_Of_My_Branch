import os
from functools import lru_cache
from app.config.settings import get_settings
from shared.infrastructure.redis_client import get_redis_client

class Bootstrap:
    _redis_client = None
    _ingestion_service = None

    @classmethod
    async def get_redis(cls):
        if cls._redis_client is None:
            cls._redis_client = await get_redis_client()
        return cls._redis_client

    @classmethod
    async def get_ingestion_service(cls):
        if cls._ingestion_service is None:
            from domains.ingestion.infrastructure.outbound.adapter_factory import get_market_data_adapter
            from domains.ingestion.infrastructure.outbound.redis_event_bus_adapter import RedisEventBusAdapter
            from domains.ingestion.infrastructure.outbound.redis_dedup_adapter import RedisDedupAdapter
            from domains.ingestion.application.services.ingestion_service import IngestionService
            
            settings = get_settings()
            redis = await cls.get_redis()
            
            market_adapter = get_market_data_adapter(redis_client=redis)
            bus = RedisEventBusAdapter(redis)
            dedup = RedisDedupAdapter(settings.RedisUrl)
            
            cls._ingestion_service = IngestionService(
                price_fetcher=market_adapter,
                option_fetcher=market_adapter,
                dedup_store=dedup,
                event_bus=bus,
                redis_client=redis
            )
        return cls._ingestion_service
