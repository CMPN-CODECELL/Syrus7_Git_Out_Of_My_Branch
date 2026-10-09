"""
File Overview: Orchestrator service managing derivatives pricing computations (Crank-Nicolson and BSM models) and caching.
"""
import json
import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional

from domains.analytics.application.services.derivatives.pde_solver import CrankNicolsonPDE
from domains.analytics.application.services.derivatives.black_scholes import BlackScholesMerton
from shared.constants import RedisKeys, TTL, Streams, Channels
from shared.infrastructure.redis_client import get_redis_client

logger = logging.getLogger(__name__)

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

class DerivativesOrchestratorService:
    async def price_options_chain(self, symbol: str) -> bool:
        """
        Loads the raw option chain, calculates fair prices under CN and BSM models, caches the result, and publishes to Pub/Sub.
        """
        symbol_upper = symbol.strip().upper()
        logger.debug("[%s] Pricing options chain...", symbol_upper)
        
        try:
            redis = await get_redis_client()
            raw_key = RedisKeys.MARKET_OPTIONS.format(symbol=symbol_upper)
            raw_data = await redis.get(raw_key)
            
            if not raw_data:
                logger.warning("[%s] Raw options data not found in cache. Cannot price.", symbol_upper)
                return False
                
            payload = json.loads(raw_data)
            
            # The structure of raw option chain under MARKET_OPTIONS is OptionChainSummaryDTO
            # Let's extract Spot, RF rate, maturity, etc.
            summary = payload.get("summary", {})
            S0 = summary.get("underlying_price", 0.0)
            if S0 == 0.0:
                # Fallback to stock price key
                price_key = RedisKeys.MARKET_PRICE.format(symbol=symbol_upper)
                price_raw = await redis.get(price_key)
                if price_raw:
                    S0 = json.loads(price_raw).get("last_price", 0.0)
            
            # Use dynamic defaults if not present
            r = summary.get("risk_free_rate", 6.5) / 100.0
            # time_to_maturity in years
            expiry_days = summary.get("expiry_days", 30)
            T = max(expiry_days, 1) / 365.0
            dividend_yield = summary.get("dividend_yield", 0.0) / 100.0
            
            strikes_data = payload.get("chain", [])
            if not strikes_data:
                logger.warning("[%s] No strikes found in option chain.", symbol_upper)
                return False
                
            # Group strikes
            strikes_map = {}
            for s in strikes_data:
                strike = s.get("strike_price")
                if strike is None:
                    continue
                if strike not in strikes_map:
                    strikes_map[strike] = {}
                    
                for side in ["call", "put"]:
                    side_data = s.get(side, {})
                    type_str = "CE" if side == "call" else "PE"
                    strikes_map[strike][type_str] = {
                        "iv": side_data.get("iv", 0.20),
                        "ltp": side_data.get("ltp", 0.0)
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

            # Cache priced chain
            cache_key = RedisKeys.MARKET_OPTIONS_PRICED.format(symbol=symbol_upper)
            cache_payload = {
                "symbol": symbol_upper,
                "chain": priced_chain,
                "last_updated": datetime.now(timezone.utc).isoformat()
            }
            await redis.set(cache_key, json.dumps(cache_payload), ex=TTL.MARKET_OPTIONS_PRICED)

            # Publish to Stream
            event_data = json.dumps({"symbol": symbol_upper, "chain": priced_chain})
            await redis.xadd(Streams.OPTIONS_PRICED, {"data": event_data}, maxlen=10000, approximate=True)

            # Publish to Pub/Sub (Live UI)
            await redis.publish(Channels.OPTIONS_UPDATED.format(symbol=symbol_upper), event_data)
            logger.debug("[%s] Option pricing complete. Priced %d strikes.", symbol_upper, len(priced_chain))
            return True
            
        except Exception as exc:
            logger.exception("[%s] Error pricing options chain", symbol_upper)
            return False
