"""
File Overview: Application service implementing ICalculateGreeksUseCasePort.
Coordinates pure domain BSM calculator with external market data adapters and option surface caches.
"""
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone

from domains.analytics.ports.interface.inbound.i_calculate_greeks_use_case_port import ICalculateGreeksUseCasePort
from domains.analytics.domain.services.bsm_calculator import BsmCalculatorDomainService

logger = logging.getLogger(__name__)


class GreeksPricingService(ICalculateGreeksUseCasePort):
    """Application Service for options pricing and Greeks analytics."""

    def __init__(self, market_data_adapter=None, surface_cache=None):
        self._adapter = market_data_adapter
        self._cache = surface_cache

    async def calculate_single_option(
        self,
        spot: float,
        strike: float,
        expiry_days: int,
        rate: float,
        volatility: float,
        option_type: str = "call",
        dividend_yield: float = 0.0,
    ) -> Dict[str, Any]:
        t = max(expiry_days, 1) / 365.0
        vol_decimal = volatility / 100.0 if volatility > 1.0 else volatility
        rate_decimal = rate / 100.0 if rate > 1.0 else rate
        div_decimal = dividend_yield / 100.0 if dividend_yield > 1.0 else dividend_yield

        price = BsmCalculatorDomainService.calculate_price(
            spot=spot,
            strike=strike,
            expiry_years=t,
            rate=rate_decimal,
            volatility=vol_decimal,
            option_type=option_type,
            dividend_yield=div_decimal,
        )

        greeks = BsmCalculatorDomainService.calculate_greeks(
            spot=spot,
            strike=strike,
            expiry_years=t,
            rate=rate_decimal,
            volatility=vol_decimal,
            option_type=option_type,
            dividend_yield=div_decimal,
        )

        return {
            "price": round(price, 4),
            "delta": round(greeks.delta, 4),
            "gamma": round(greeks.gamma, 6),
            "theta": round(greeks.theta, 4),
            "vega": round(greeks.vega, 4),
            "rho": round(greeks.rho, 4),
        }

    async def get_ticker_analytics(self, symbol: str) -> Dict[str, Any]:
        """Fetch live ticker data via market data adapter or surface cache."""
        symbol_clean = symbol.strip().upper()
        if self._cache:
            cached = await self._cache.get_cached_surface(symbol_clean)
            if cached:
                return cached

        if not self._adapter:
            return {"symbol": symbol_clean, "status": "NO_ADAPTER"}

        dtos = await self._adapter.fetch_option_chain(symbol_clean)
        live_price_data = await self._adapter.fetch_price(symbol_clean)
        
        spot_price = dtos[0].underlying_price if dtos else (float(live_price_data.get("last_price", 0.0)) if live_price_data else 0.0)

        chains = {}
        expiry_dates = set()
        for dto in dtos or []:
            if not dto.expiry:
                continue
            expiry_dates.add(dto.expiry)
            if dto.expiry not in chains:
                chains[dto.expiry] = []
            chains[dto.expiry].append({
                "strike": dto.strike,
                "type": dto.option_type,
                "last_price": dto.ltp,
                "oi": dto.oi,
                "volume": dto.volume,
                "iv": dto.iv,
                "bid": dto.bid,
                "bid_qty": dto.bid_qty,
                "ask": dto.ask,
                "ask_qty": dto.ask_qty,
                "expiry": dto.expiry,
            })

        result = {
            "symbol": symbol_clean,
            "stock_price": spot_price,
            "expiry_dates": sorted(list(expiry_dates)),
            "chains": chains,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        if self._cache:
            await self._cache.save_surface(symbol_clean, result)

        return result
