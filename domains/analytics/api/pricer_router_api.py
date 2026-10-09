"""
File Overview: FastAPI router for options pricer BSM calculations and live ticker data queries.

All Functions/Classes:
- pricer_router: APIRouter for pricer services.
- get_ticker_parameters: GET endpoint fetching real-time Redis or dynamic live options parameters for a symbol.
- calculate_bsm: POST endpoint executing BSM pricer and returning intermediate / final option edge parameters.
"""
import math
import hashlib
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import numpy as np
from scipy.stats import norm
from fastapi import APIRouter, HTTPException

from shared.utils.symbol_validator import SymbolValidator
from shared.infrastructure.redis_client import get_redis_client
from shared.constants import RedisKeys
from domains.analytics.api.schemas import (
    PricerTickerDataResponse,
    BSMCalculateRequest,
    BSMCalculateResponse,
    OptionChainRow,
    OptionChainSide,
)


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pricer", tags=["pricer"])


from functools import lru_cache
from app.config.settings import get_settings


def _generated_at() -> str:
    return datetime.now(timezone.utc).isoformat()


@lru_cache(maxsize=128)
def _get_historical_volatility(symbol: str) -> float:
    """Compute rolling 30-day annualized historical volatility from historical prices."""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1mo")
        if hist is not None and len(hist) > 5:
            log_returns = np.log(hist["Close"] / hist["Close"].shift(1)).dropna()
            hv = float(log_returns.std() * np.sqrt(252) * 100.0)
            return round(hv, 2) if not np.isnan(hv) else 0.0
    except Exception:
        pass
    return 0.0


@router.get("/ticker/{symbol}", response_model=PricerTickerDataResponse)
async def get_ticker_parameters(symbol: str):
    """
    Get live options pricing parameters for the BSM Pricer inputs.
    Tries to read live options chain cache from Redis first.
    """
    symbol_upper = symbol.strip().upper()
    # Basic format check: must be alphanumeric (allowing dot, hyphen, caret)
    clean_format = symbol_upper.replace(".", "").replace("-", "").replace("^", "")
    if not clean_format or not clean_format.isalnum():
        raise HTTPException(
            status_code=400,
            detail=f"Symbol '{symbol_upper}' is invalid or not supported."
        )

    symbol_clean = SymbolValidator.get_clean_symbol(symbol_upper)
    settings = get_settings()
    rf_rate = settings.DefaultRiskFreeRateInr if ("NS" in symbol_upper or symbol_clean in {"NIFTY", "BANKNIFTY", "FINNIFTY"}) else settings.DefaultRiskFreeRateUsd
    
    raw_cached = None
    price_cached = None
    redis = None
    try:
        redis = await get_redis_client()
        # Attempt to load options cache
        raw_key = RedisKeys.MARKET_OPTIONS.format(symbol=symbol_clean)
        raw_cached = await redis.get(raw_key)

        # Attempt to load spot price cache
        price_key = RedisKeys.MARKET_PRICE.format(symbol=symbol_clean)
        price_cached = await redis.get(price_key)
    except Exception as exc:
        logger.warning("[%s] Failed connecting to Redis, falling back to direct adapter fetch: %s", symbol_clean, exc)

    if not raw_cached:
        # Try live fetch
        from domains.ingestion.infrastructure.outbound.adapter_factory import get_market_data_adapter
        adapter = get_market_data_adapter()

        dtos = []
        live_price_data = None
        try:
            dtos = await adapter.fetch_option_chain(symbol_clean)
            live_price_data = await adapter.fetch_price(symbol_clean)
        except Exception as fetch_exc:
            logger.error("[%s] Dynamic live fetch failed: %s", symbol_clean, fetch_exc)
        finally:
            await adapter.close()

        if dtos:
            spot_price = dtos[0].underlying_price
            if spot_price <= 0 and live_price_data:
                spot_price = float(live_price_data.get("last_price", 0.0))
            
            chains = {}
            expiry_dates = set()
            for dto in dtos:
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
                    "expiry": dto.expiry
                })
            
            data = {
                "symbol": symbol_clean,
                "spot_price": spot_price,
                "expiry_dates": sorted(list(expiry_dates)),
                "chains": chains,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "summary": {"total_strikes": len(set(d.strike for d in dtos))}
            }
            
            if redis:
                try:
                    raw_key = RedisKeys.MARKET_OPTIONS.format(symbol=symbol_clean)
                    await redis.set(raw_key, json.dumps(data, default=str), ex=60)
                    
                    price_key = RedisKeys.MARKET_PRICE.format(symbol=symbol_clean)
                    p_data = {
                        "symbol": symbol_clean,
                        "last_price": spot_price,
                        "last_updated": datetime.now(timezone.utc).isoformat()
                    }
                    await redis.set(price_key, json.dumps(p_data, default=str), ex=60)
                except Exception as cache_exc:
                    logger.warning("[%s] Failed caching dynamically fetched options to Redis: %s", symbol_clean, cache_exc)
            
            raw_cached = json.dumps(data, default=str)
        elif live_price_data:
            spot_price = float(live_price_data.get("last_price", 0.0))
            data = {
                "symbol": symbol_clean,
                "spot_price": spot_price,
                "expiry_dates": [],
                "chains": {},
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "summary": {"total_strikes": 0}
            }
            if redis:
                try:
                    raw_key = RedisKeys.MARKET_OPTIONS.format(symbol=symbol_clean)
                    await redis.set(raw_key, json.dumps(data, default=str), ex=60)
                    
                    price_key = RedisKeys.MARKET_PRICE.format(symbol=symbol_clean)
                    p_data = {
                        "symbol": symbol_clean,
                        "last_price": spot_price,
                        "last_updated": datetime.now(timezone.utc).isoformat()
                    }
                    await redis.set(price_key, json.dumps(p_data, default=str), ex=60)
                except Exception as cache_exc:
                    logger.warning("[%s] Failed caching price data to Redis: %s", symbol_clean, cache_exc)

            raw_cached = json.dumps(data, default=str)
        else:
            raw_cached = None

    if raw_cached:
        try:
            chain_data = json.loads(raw_cached)
            spot = float(chain_data.get("spot_price", 0.0))
            if spot <= 0 and price_cached:
                p_data = json.loads(price_cached)
                spot = float(p_data.get("last_price", 0.0))

            expiries = chain_data.get("expiry_dates", [])
            chains = chain_data.get("chains", {})

            if not expiries or not chains:
                return PricerTickerDataResponse(
                    symbol=symbol_clean,
                    stock_price=spot,
                    implied_volatility=0.0,
                    historical_volatility=_get_historical_volatility(symbol_clean),
                    bid_price=None,
                    ask_price=None,
                    open_interest=0,
                    volume=0,
                    strike_price=0.0,
                    expiry_days=0,
                    risk_free_rate=rf_rate,
                    dividend_yield=0.0,
                    expiry_dates=[],
                    option_chains={},
                    generated_at=_generated_at(),
                    source="live_market_fetch" if spot > 0 else "market_data_unavailable",
                    stale=False,
                    partial=False,
                    status="COMPLETED",
                )

            if spot > 0 and expiries and chains:
                # Target nearest expiry
                nearest_exp = expiries[0]
                strikes_data = chains.get(nearest_exp, [])

                # Find near-the-money call option
                nearest_strike_opt = None
                min_diff = float("inf")
                for opt in strikes_data:
                    diff = abs(opt["strike"] - spot)
                    if diff < min_diff:
                        min_diff = diff
                        nearest_strike_opt = opt

                if nearest_strike_opt:
                    # Calculate implied/historical params
                    # Expiry days estimation
                    try:
                        exp_dt = datetime.strptime(nearest_exp, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                        delta = (exp_dt - datetime.now(timezone.utc)).days
                        expiry_days = max(delta, 1)
                    except Exception:
                        expiry_days = 30

                    ltp = float(nearest_strike_opt.get("last_price", 0.0))
                    raw_bid = nearest_strike_opt.get("bid")
                    raw_ask = nearest_strike_opt.get("ask")
                    bid = float(raw_bid) if raw_bid is not None and float(raw_bid) > 0 else None
                    ask = float(raw_ask) if raw_ask is not None and float(raw_ask) > 0 else None
                    
                    iv = float(nearest_strike_opt.get("iv", 0.0) or 0.0)
                    if iv > 0.0 and iv < 1.0:
                        iv *= 100.0
                    elif iv <= 0.0 and ltp > 0 and spot > 0:
                        # Attempt BSM IV solution
                        try:
                            from domains.analytics.domain.black_scholes import BSMCalculations
                            solved_iv = BSMCalculations.implied_volatility(
                                price=ltp,
                                S=spot,
                                K=float(nearest_strike_opt.get("strike", spot)),
                                T=max(expiry_days, 1) / 365.0,
                                r=rf_rate / 100.0,
                                option_type="call"
                            )
                            if solved_iv and solved_iv > 0:
                                iv = round(solved_iv * 100.0, 2)
                        except Exception:
                            iv = 0.0

                    # Parse option chains for ALL expiries from Redis
                    option_chains = {}
                    for exp_date in expiries:
                        exp_strikes = chains.get(exp_date, [])
                        rows_by_strike = {}
                        for opt in exp_strikes:
                            strike = float(opt["strike"])
                            if strike not in rows_by_strike:
                                rows_by_strike[strike] = {
                                    "strike_price": strike,
                                    "call": {"oi": 0, "chng_in_oi": 0, "volume": 0, "iv": 0.0, "ltp": 0.0, "chng": 0.0, "bid_qty": 0, "bid": 0.0, "ask": 0.0, "ask_qty": 0},
                                    "put": {"oi": 0, "chng_in_oi": 0, "volume": 0, "iv": 0.0, "ltp": 0.0, "chng": 0.0, "bid_qty": 0, "bid": 0.0, "ask": 0.0, "ask_qty": 0}
                                }
                            opt_type = opt.get("type", "").upper()
                            side = "call" if opt_type in ("CE", "CALL") else "put"
                            
                            iv_val = float(opt.get("iv", 0.0) or 0.0)
                            if iv_val > 0.0 and iv_val < 1.0:
                                iv_val *= 100.0
                            elif iv_val <= 0.0:
                                iv_val = 0.0
                                
                            ltp_val = float(opt.get("last_price", 0.0) or 0.0)
                            
                            b_val = float(opt.get("bid", 0.0) or 0.0)
                            a_val = float(opt.get("ask", 0.0) or 0.0)
                            b_qty = int(opt.get("bid_qty", 0) or 0)
                            a_qty = int(opt.get("ask_qty", 0) or 0)
                            
                            rows_by_strike[strike][side] = {
                                "oi": int(opt.get("oi", 0) or 0),
                                "chng_in_oi": int(opt.get("chng_in_oi", 0) or 0),
                                "volume": int(opt.get("volume", 0) or 0),
                                "iv": iv_val,
                                "ltp": ltp_val,
                                "chng": float(opt.get("change", 0.0) or 0.0),
                                "bid_qty": b_qty if b_qty > 0 else None,
                                "bid": b_val if b_val > 0 else None,
                                "ask": a_val if a_val > 0 else None,
                                "ask_qty": a_qty if a_qty > 0 else None
                            }
                            
                        sorted_rows = []
                        for strike in sorted(rows_by_strike.keys()):
                            sorted_rows.append(OptionChainRow(
                                strike_price=strike,
                                call=OptionChainSide(**rows_by_strike[strike]["call"]),
                                put=OptionChainSide(**rows_by_strike[strike]["put"])
                            ))
                        option_chains[exp_date] = sorted_rows

                    return PricerTickerDataResponse(
                        symbol=symbol_clean,
                        stock_price=spot,
                        implied_volatility=iv,
                        historical_volatility=_get_historical_volatility(symbol_clean),
                        bid_price=bid,
                        ask_price=ask,
                        open_interest=int(nearest_strike_opt.get("oi", 0) or 0),
                        volume=int(nearest_strike_opt.get("volume", 0) or 0),
                        strike_price=float(nearest_strike_opt.get("strike", spot)),
                        expiry_days=expiry_days,
                        risk_free_rate=rf_rate,
                        dividend_yield=0.0,
                        expiry_dates=expiries,
                        option_chains=option_chains,
                        generated_at=_generated_at(),
                        source="redis_cache",
                        stale=False,
                        partial=False,
                        status="COMPLETED",
                    )
        except Exception as exc:
            logger.warning("[%s] Failed fetching real-time pricer options params from Redis: %s", symbol_clean, exc)

    # Real market data unavailable across all sources (Groww, yfinance, NSE)
    raise HTTPException(
        status_code=503,
        detail=f"Live market data is currently unavailable for '{symbol_clean}' across all market sources."
    )


@router.post("/calculate", response_model=BSMCalculateResponse)
def calculate_bsm(request: BSMCalculateRequest):
    """
    Run high-precision Black-Scholes-Merton pricing logic on inputs.
    """
    S0 = request.S0
    K = request.K
    T_days = request.T_days
    r = request.r
    sigma = request.sigma
    option_type = request.option_type.strip().lower()
    q = request.q

    if S0 <= 0 or K <= 0 or T_days < 0 or sigma <= 0:
        raise HTTPException(
            status_code=422,
            detail="Stock price (S0), Strike (K), Expiry (T_days), and Volatility (sigma) must be greater than zero."
        )

    # Conversions
    T_years = max(T_days, 0.001) / 365.0
    r_frac = r / 100.0
    sigma_frac = sigma / 100.0
    q_frac = q / 100.0

    # Intermediate d1, d2 formulas
    try:
        d1 = (math.log(S0 / K) + (r_frac - q_frac + 0.5 * sigma_frac ** 2) * T_years) / (sigma_frac * math.sqrt(T_years))
        d2 = d1 - sigma_frac * math.sqrt(T_years)
    except ZeroDivisionError:
        raise HTTPException(status_code=422, detail="Volatility or Time to Expiry is too close to zero.")

    # Cumulative normal probabilities
    Nd1 = norm.cdf(d1)
    Nd2 = norm.cdf(d2)

    # Solvers
    if option_type == "call":
        fair_val = S0 * math.exp(-q_frac * T_years) * Nd1 - K * math.exp(-r_frac * T_years) * Nd2
    elif option_type == "put":
        fair_val = K * math.exp(-r_frac * T_years) * norm.cdf(-d2) - S0 * math.exp(-q_frac * T_years) * norm.cdf(-d1)
    else:
        raise HTTPException(
            status_code=400,
            detail="Option type must be 'call' or 'put'."
        )

    fair_val = max(fair_val, 0.0)

    # Edge computation
    edge = None
    if request.market_mid is not None and request.market_mid > 0:
        edge = fair_val - request.market_mid

    return BSMCalculateResponse(
        S0=S0,
        K=K,
        T_years=round(T_years, 4),
        r=r,
        sigma=sigma,
        option_type=option_type,
        q=q,
        d1=round(d1, 4),
        d2=round(d2, 4),
        Nd1=round(Nd1, 4),
        Nd2=round(Nd2, 4),
        fair_value=round(fair_val, 2),
        market_mid=request.market_mid,
        edge=round(edge, 2) if edge is not None else None,
    )
