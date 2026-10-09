import asyncio
import json
from shared.infrastructure.redis_client import get_redis_client
from shared.constants import RedisKeys

async def diagnose():
    symbol = "NIFTY"
    print(f"--- Diagnostics for {symbol} ---")
    
    redis = await get_redis_client()

    # Check Redis Price
    price_key = RedisKeys.MARKET_PRICE.format(symbol=symbol)
    price_exists = await redis.exists(price_key)
    price_val = await redis.get(price_key) if price_exists else None
    print(f"Redis: Price exists: {price_exists} (Value: {price_val[:100] if price_val else 'None'})")

    # Check Redis Options
    options_key = RedisKeys.MARKET_OPTIONS.format(symbol=symbol)
    options_exists = await redis.exists(options_key)
    options_val = await redis.get(options_key) if options_exists else None
    print(f"Redis: Options exists: {options_exists} (Value: {options_val[:100] if options_val else 'None'})")

if __name__ == "__main__":
    asyncio.run(diagnose())
