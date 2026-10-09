"""
File Overview: PDE Solver worker consuming options data from Redis Streams.
Calculates fair prices using Crank-Nicolson finite difference method.

All Functions/Classes:
- OptionsPricingSubscriber: Real-time derivatives pricing engine. Data: raw ticks -> priced chains.
- start_consuming: Async listen loop. Data: Redis stream data -> process_event.
- process_event: Core orchestrator. Data: raw payload -> Redis Streams/PubSub.
- main: Entry point coroutine. Data: Environment config -> Engine bootstrap.

Endpoints/APIs: None

Database Tables:
- Redis (Streams: stream:options.raw_fetched -> stream:options.priced, PubSub).
"""
import json
import asyncio
import logging
import os
from datetime import datetime, timezone

from redis.asyncio import Redis
from domains.analytics.application.services.derivatives.pde_solver import CrankNicolsonPDE
from domains.analytics.application.services.derivatives.black_scholes import BlackScholesMerton
from shared.constants import RedisKeys, TTL, Streams, Channels

logger = logging.getLogger("options_pricing_subscriber")


def _solve_strike_sync(S0: float, strike: float, T: float, r: float, call_iv: float, put_iv: float, dividend_yield: float, live_call: float, live_put: float) -> dict:
    """Helper to solve single strike CE/PE pricing synchronously in worker thread."""
    # Call Price (Crank-Nicolson PDE)
    call_solver = CrankNicolsonPDE(S0, strike, T, r, call_iv, 'call')
    call_price = call_solver.solve()

    # Put Price (Crank-Nicolson PDE)
    put_solver = CrankNicolsonPDE(S0, strike, T, r, put_iv, 'put')
    put_price = put_solver.solve()

    # Call Price (Black-Scholes-Merton Analytical)
    bs_call_solver = BlackScholesMerton(S0, strike, T, r, call_iv, 'call', q=dividend_yield)
    bs_call_price = bs_call_solver.solve()

    # Put Price (Black-Scholes-Merton Analytical)
    bs_put_solver = BlackScholesMerton(S0, strike, T, r, put_iv, 'put', q=dividend_yield)
    bs_put_price = bs_put_solver.solve()

    return {
        "strike": strike,
        "fair_call": round(call_price, 2),
        "fair_put": round(put_price, 2),
        "call_iv": call_iv,
        "put_iv": put_iv,
        "bs_fair_call": round(bs_call_price, 2),
        "bs_fair_put": round(bs_put_price, 2),
        "live_call": round(live_call, 2) if live_call is not None else 0.0,
        "live_put": round(live_put, 2) if live_put is not None else 0.0
    }


class OptionsPricingSubscriber:
    def __init__(self, redis_client: Redis):
        self.redis = redis_client
        self.consume_stream = Streams.OPTIONS_RAW_FETCHED
        self.publish_stream = Streams.OPTIONS_PRICED
        self.pubsub_channel = Channels.OPTIONS_UPDATED

    async def start_consuming(self):
        # WARNING: Using "$" means we only read NEW messages — any messages
        # published while this subscriber was down are lost.  For durable
        # processing, migrate to XREADGROUP with a consumer group (like
        # DurableEventStream in shared/infrastructure/event_bus/streams.py).
        last_id = "$"
        logger.info("PDE Solver Engine listening for raw options data...")

        while True:
            # Block and wait for new raw options data
            events = await self.redis.xread({self.consume_stream: last_id}, count=1, block=5000)

            for stream, messages in events:
                for message_id, payload in messages:
                    try:
                        await self.process_event(payload)
                    except Exception as exc:
                        logger.error("Failed to process options event %s: %s", message_id, exc, exc_info=True)
                    last_id = message_id

    async def process_event(self, payload: dict):
        symbol = payload[b"symbol"].decode("utf-8").upper()
        data = json.loads(payload[b"data"].decode("utf-8"))

        S0 = data["spot_price"]
        r = data["risk_free_rate"]
        T = data["time_to_maturity"]
        dividend_yield = data.get("dividend_yield", 0.0)

        # Group strikes by price to solve CE/PE together
        strikes_map = {}
        for s in data.get("strikes_data", []):
            strike = s["strike"]
            if strike not in strikes_map:
                strikes_map[strike] = {}
            strikes_map[strike][s["type"]] = {
                "iv": s.get("iv", 0.20),
                "ltp": s.get("ltp", 0.0)
            }

        tasks = []
        for strike, type_data in strikes_map.items():
            call_iv = type_data.get("CE", {}).get("iv", 0.20)
            put_iv = type_data.get("PE", {}).get("iv", 0.20)
            live_call = type_data.get("CE", {}).get("ltp", 0.0)
            live_put = type_data.get("PE", {}).get("ltp", 0.0)

            tasks.append(
                asyncio.to_thread(
                    _solve_strike_sync,
                    S0, strike, T, r, call_iv, put_iv, dividend_yield, live_call, live_put
                )
            )

        priced_chain = await asyncio.gather(*tasks)

        # Cache in Redis for high performance read-model API querying
        cache_key = RedisKeys.MARKET_OPTIONS_PRICED.format(symbol=symbol)
        cache_payload = {
            "symbol": symbol,
            "chain": priced_chain,
            "last_updated": datetime.now(timezone.utc).isoformat()
        }
        await self.redis.set(cache_key, json.dumps(cache_payload), ex=TTL.MARKET_OPTIONS_PRICED)

        # Publish Durable Event (for read-model updates)
        event_data = json.dumps({"symbol": symbol, "chain": priced_chain})
        await self.redis.xadd(self.publish_stream, {"data": event_data})

        # Publish Ephemeral Event (Live UX update)
        await self.redis.publish(self.pubsub_channel.format(symbol=symbol), event_data)
        logger.debug("Priced %d strikes for %s. Surface published.", len(priced_chain), symbol)


async def main():
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    redis_client = Redis.from_url(redis_url)
    try:
        subscriber = OptionsPricingSubscriber(redis_client)
        await subscriber.start_consuming()
    finally:
        await redis_client.aclose()


if __name__ == "__main__":
    try:
        import uvloop
        uvloop.install()
    except ImportError:
        pass
    asyncio.run(main())
