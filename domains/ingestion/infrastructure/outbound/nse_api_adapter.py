"""
File Overview: Outbound adapter for NSE India and yfinance. Handles market price and option chain retrieval.

All Functions/Classes:
- MarketPriceFetcher: Price snapshot engine via yfinance. Take symbol and send OHLCV data.
- OptionChainFetcher: Derivatives data engine via NSE V3 API. Take symbol and send structured chain with spot price.
- nse_api_adapter: Port implementation for market data. Take symbol and send raw_tick_dto list via option chain fetcher.

Endpoints/APIs: NSE India API, yfinance API

Database Tables: None
"""

import os
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, List

from domains.ingestion.ports.interface.outbound.i_option_chain_source_port import IOptionChainSourcePort
from domains.ingestion.ports.interface.outbound.i_market_price_source_port import IMarketPriceSourcePort
from domains.ingestion.application.dto.raw_tick_dto import RawTickDTO

import aiohttp
import yfinance as yf
import pandas as pd
import numpy as np
import hashlib
import pytz

from shared.constants import MarketStatus, INDEX_SYMBOLS
from shared.utils.symbol_validator import SymbolValidator

logger = logging.getLogger(__name__)

# ── NSE India API Configuration ────────────────────────────────

_NSE_BASE_URL = "https://www.nseindia.com"
_NSE_CONTRACT_INFO_URL = "https://www.nseindia.com/api/option-chain-contract-info?symbol={symbol}"
_NSE_OPTION_CHAIN_V3_URL = "https://www.nseindia.com/api/option-chain-v3?type={type}&symbol={symbol}&expiry={expiry}"

_NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}

_NSE_API_HEADERS = {
    "host": "www.nseindia.com",
    "User-Agent": _NSE_HEADERS["User-Agent"],
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Referer": "https://www.nseindia.com/option-chain",
    "X-Requested-With": "XMLHttpRequest",
    "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}

# ── Symbol Mapping for yfinance ─────────────────────────────────

_YFINANCE_SYMBOL_MAP = {
    "NIFTY": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "FINNIFTY": "^CNXFIN",
}


def _to_yfinance_symbol(symbol: str) -> str:
    """Convert watchlist symbol to yfinance ticker."""
    upper = symbol.upper()
    if upper in _YFINANCE_SYMBOL_MAP:
        return _YFINANCE_SYMBOL_MAP[upper]
    
    # If it's already an index or has a suffix/special char, leave it
    if "^" in upper or "." in upper:
        return upper
        
    # Standard Indian stock symbols on yfinance need .NS suffix
    return f"{upper}.NS"


def _get_market_status(now_dt: Optional[datetime] = None) -> MarketStatus:
    """
    Determine if Indian market (NSE) is currently open.
    Market hours: 9:15 AM to 3:30 PM IST, Monday to Friday.
    """
    ist = pytz.timezone("Asia/Kolkata")
    if now_dt is not None:
        # Ensure it has timezone info or is localized to IST
        if now_dt.tzinfo is None:
            now = ist.localize(now_dt)
        else:
            now = now_dt.astimezone(ist)
    else:
        now = datetime.now(ist)

    # Weekend check
    if now.weekday() >= 5:
        return MarketStatus.CLOSED

    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)

    if now < market_open:
        return MarketStatus.PRE_MARKET
    elif now > market_close:
        return MarketStatus.POST_MARKET
    else:
        return MarketStatus.OPEN


# ═══════════════════════════════════════════════════════════════
# Market Price Fetcher (yfinance)
# ═══════════════════════════════════════════════════════════════

class NseApiAdapter(IMarketPriceSourcePort, IOptionChainSourcePort):
    """
    Unified adapter for market data via NSE India and yfinance.
    Implements both market price and option chain ports.
    """

    def __init__(self) -> None:
        self._Session: Optional[aiohttp.ClientSession] = None
        self._CookieRefreshTime: Optional[datetime] = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        current_loop = asyncio.get_running_loop()
        if self._Session is not None and not self._Session.closed:
            # Recreate session if bound to a different event loop (e.g. inside different Celery tasks)
            if getattr(self._Session, "_loop", None) is not current_loop:
                try:
                    await self._Session.close()
                except Exception:
                    pass
                self._Session = None

        if self._Session is None or self._Session.closed:
            self._Session = aiohttp.ClientSession(
                headers=_NSE_HEADERS,
                timeout=aiohttp.ClientTimeout(total=30),
            )
        return self._Session

    async def close(self) -> None:
        if self._Session and not self._Session.closed:
            await self._Session.close()

    # ── Market Price (yfinance) ─────────────────────────────────

    async def fetch_price(self, symbol: str) -> Optional[dict]:
        """Fetches latest OHLCV snapshot via yfinance (non-blocking)."""
        yf_symbol = _to_yfinance_symbol(symbol)
        market_status = _get_market_status()

        try:
            loop = asyncio.get_running_loop()
            data = await loop.run_in_executor(None, self._fetch_price_sync, yf_symbol)
            if data:
                data["symbol"] = symbol.upper()
                data["market_status"] = market_status.value
            return data
        except Exception as exc:
            logger.error("[%s] yfinance fetch error: %s", symbol, exc)
            return None

    @staticmethod
    def _fetch_price_sync(yf_symbol: str) -> Optional[dict]:
        try:
            ticker = yf.Ticker(yf_symbol)
            hist = ticker.history(period="5d")
            if hist.empty: return None

            hist.columns = [c.lower() for c in hist.columns]
            latest = hist.iloc[-1]
            prev = hist.iloc[-2] if len(hist) > 1 else latest

            last_price = float(latest["close"])
            prev_close = float(prev["close"])
            change_pct = round(((last_price - prev_close) / prev_close) * 100, 2) if prev_close else 0.0

            # Extract dividend yield (usually as float ratio e.g. 0.015 for 1.5%)
            div_yield = ticker.info.get("dividendYield") or ticker.info.get("trailingAnnualDividendYield") or 0.0

            return {
                "last_price": round(last_price, 2),
                "open": round(float(latest["open"]), 2),
                "high": round(float(latest["high"]), 2),
                "low": round(float(latest["low"]), 2),
                "volume": int(latest.get("volume", 0)),
                "previous_close": round(prev_close, 2),
                "change_percent": change_pct,
                "currency": ticker.info.get("currency", "INR"),
                "dividend_yield": float(div_yield),
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:
            logger.error("[%s] _fetch_price_sync error: %s", yf_symbol, exc)
            return None

    # ── Option Chain (NSE V3 API) ───────────────────────────────

    async def fetch_expiry_dates(self, symbol: str) -> List[str]:
        """Fetches available option expiry dates for symbol from NSE or fallback."""
        try:
            fallback_chain = await self._fetch_option_chain_raw(symbol)
            if fallback_chain and "expiry_dates" in fallback_chain:
                return fallback_chain["expiry_dates"]
        except Exception as e:
            logger.warning("[%s] Failed to fetch expiry dates: %s", symbol, e)
        return []

    async def fetch_option_chain(self, symbol: str) -> List[RawTickDTO]:
        """Fetches full option chain and returns list of RawTickDTOs using real market data."""
        data = await self._fetch_option_chain_raw(symbol)
        if not data:
            logger.warning("[%s] Options data is unavailable across all market sources", symbol)
            return []

        dtos = []
        chains = data.get("chains", {})
        spot_price = data.get("spot_price", 0.0)
        for expiry, ticks in chains.items():
            for t in ticks:
                dtos.append(RawTickDTO(
                    symbol=symbol.upper(),
                    expiry=expiry,
                    strike=t["strike"],
                    option_type=t["type"],
                    oi=t["oi"],
                    volume=t["volume"],
                    ltp=t["last_price"],
                    iv=t.get("iv", 0.0),
                    bid=float(t.get("bid", 0.0) or 0.0),
                    bid_qty=int(t.get("bid_qty", 0) or 0),
                    ask=float(t.get("ask", 0.0) or 0.0),
                    ask_qty=int(t.get("ask_qty", 0) or 0),
                    underlying_price=spot_price,
                    timestamp=datetime.now(timezone.utc)
                ))
        return dtos

    async def _fetch_option_chain_raw(self, symbol: str) -> Optional[dict]:
        # Precedence 1: NSE Webscraper API (includes real bid/ask orderbook depth)
        logger.info("[%s] Attempting option chain retrieval via NSE Webscraper", symbol)
        nse_data = await self._fetch_nse_webscraper_options(symbol)
        if nse_data and nse_data.get("chains"):
            logger.info("[%s] Option chain retrieved via NSE Webscraper with real bid/ask quotes", symbol)
            return nse_data

        # Precedence 2: Yahoo Finance Fallback
        logger.info("[%s] Fallback: Attempting option chain retrieval via Yahoo Finance", symbol)
        return await self._fetch_yfinance_options_fallback(symbol)

    async def _fetch_nse_webscraper_options(self, symbol: str, retry_count: int = 0) -> Optional[dict]:
        session = await self._ensure_session()
        await self._soft_initialise(symbol)

        clean_sym = SymbolValidator.get_clean_symbol(symbol.upper())
        is_nse = clean_sym in INDEX_SYMBOLS or clean_sym.endswith(".NS") or clean_sym.endswith(".BO")

        if not is_nse:
            return None

        clean_name = symbol.upper().replace(".NS", "").replace(".BO", "")
        m_type = "Indices" if clean_name in INDEX_SYMBOLS else "Equity"

        try:
            # 1. Get Expiries
            info_url = _NSE_CONTRACT_INFO_URL.format(symbol=clean_name)
            async with session.get(info_url, headers=_NSE_API_HEADERS) as resp:
                if resp.status == 401 and retry_count < 2:
                    await self._soft_initialise(symbol, force=True)
                    return await self._fetch_nse_webscraper_options(symbol, retry_count + 1)
                
                if resp.status != 200:
                    return None
                
                info_data = await resp.json()
                expiries = info_data.get("expiryDates") or info_data.get("metadata", {}).get("expiryDates", [])
                
            if not expiries:
                return None

            # 2. Fetch v3 chain for the first 2 expiries
            combined_data = {"records": {"underlyingValue": 0, "expiryDates": expiries, "data": []}}
            for exp in expiries[:2]:
                v3_url = _NSE_OPTION_CHAIN_V3_URL.format(type=m_type, symbol=clean_name, expiry=exp)
                async with session.get(v3_url, headers=_NSE_API_HEADERS) as resp:
                    if resp.status == 200:
                        raw_v3 = await resp.json()
                        v3_ticks = raw_v3.get("data", []) or raw_v3.get("records", {}).get("data", [])
                        if v3_ticks:
                            combined_data["records"]["data"].extend(v3_ticks)
                            spot = raw_v3.get("metadata", {}).get("underlyingValue", 0) or raw_v3.get("records", {}).get("underlyingValue", 0)
                            if spot: combined_data["records"]["underlyingValue"] = spot

            if not combined_data["records"]["data"]:
                return None

            return self._parse_option_chain(symbol, combined_data)
        except Exception as exc:
            logger.warning("[%s] NSE Webscraper fetch error: %s", symbol, exc)
            return None

    async def _soft_initialise(self, symbol: str, force: bool = False) -> None:
        session = await self._ensure_session()
        now = datetime.now(timezone.utc)
        if not force and self._CookieRefreshTime and (now - self._CookieRefreshTime).total_seconds() < 600:
            return

        clean_name = symbol.upper().replace(".NS", "").replace(".BO", "")
        try:
            async with session.get(_NSE_BASE_URL, headers=_NSE_HEADERS):
                await asyncio.sleep(0.5)
            url = f"https://www.nseindia.com/option-chain?symbol={clean_name}"
            async with session.get(url, headers=_NSE_HEADERS):
                self._CookieRefreshTime = now
                await asyncio.sleep(0.5)
        except Exception as exc:
            logger.error("[%s] Session init failed: %s", clean_name, exc)

    async def _fetch_yfinance_options_fallback(self, symbol: str) -> Optional[dict]:
        try:
            yf_symbol = _to_yfinance_symbol(symbol)
            ticker = yf.Ticker(yf_symbol)
            expiries = ticker.options
            if not expiries: return None

            chains = {}
            spot = ticker.fast_info.get("last_price", 0) if ticker.fast_info else 0
            
            for exp in expiries[:2]:
                opt = ticker.option_chain(exp)
                ticks = []
                for _, r in opt.calls.iterrows():
                    ticks.append({
                        "strike": float(r["strike"]), "type": "CE", "last_price": float(r["lastPrice"]),
                        "oi": int(r.get("openInterest", 0)), "volume": int(r.get("volume", 0)),
                        "bid": float(r.get("bid", 0.0) or 0.0), "ask": float(r.get("ask", 0.0) or 0.0),
                        "expiry": exp
                    })
                for _, r in opt.puts.iterrows():
                    ticks.append({
                        "strike": float(r["strike"]), "type": "PE", "last_price": float(r["lastPrice"]),
                        "oi": int(r.get("openInterest", 0)), "volume": int(r.get("volume", 0)),
                        "bid": float(r.get("bid", 0.0) or 0.0), "ask": float(r.get("ask", 0.0) or 0.0),
                        "expiry": exp
                    })
                chains[exp] = ticks
            
            return {"symbol": symbol.upper(), "spot_price": float(spot), "expiry_dates": list(expiries), "chains": chains}
        except Exception:
            return None

    @staticmethod
    def _parse_option_chain(symbol: str, data: dict) -> Optional[dict]:
        records = data.get("records", {})
        underlying = records.get("underlyingValue", 0)
        expiry_dates_raw = records.get("expiryDates", [])
        all_data = records.get("data", [])

        chains: dict[str, list[dict]] = {}
        for row in all_data:
            strike = row.get("strikePrice")
            expiry = NseApiAdapter._parse_nse_date(row.get("expiryDate") or row.get("expiryDates", ""))
            if not strike or not expiry: continue

            if expiry not in chains: chains[expiry] = []
            for opt_key in ["CE", "PE"]:
                opt = row.get(opt_key)
                if opt:
                    lp = opt.get("lastPrice", 0)
                    if lp > 0:
                        bid_p = float(opt.get("buyPrice1", 0.0) or opt.get("bid", 0.0) or 0.0)
                        bid_q = int(opt.get("buyQuantity1", 0) or opt.get("bid_qty", 0) or 0)
                        ask_p = float(opt.get("sellPrice1", 0.0) or opt.get("ask", 0.0) or 0.0)
                        ask_q = int(opt.get("sellQuantity1", 0) or opt.get("ask_qty", 0) or 0)
                        chains[expiry].append({
                            "strike": float(strike), "type": opt_key, "last_price": float(lp),
                            "oi": int(opt.get("openInterest", 0)), "volume": int(opt.get("totalTradedVolume", 0)),
                            "iv": float(opt.get("impliedVolatility", 0.0)),
                            "bid": bid_p, "bid_qty": bid_q, "ask": ask_p, "ask_qty": ask_q,
                            "expiry": expiry
                        })
        return {"symbol": symbol.upper(), "spot_price": float(underlying), "expiry_dates": expiry_dates_raw, "chains": chains}

    @staticmethod
    def _parse_nse_date(date_str: str) -> Optional[str]:
        months = {"Jan":"01","Feb":"02","Mar":"03","Apr":"04","May":"05","Jun":"06","Jul":"07","Aug":"08","Sep":"09","Oct":"10","Nov":"11","Dec":"12"}
        try:
            d, m, y = date_str.split("-")
            return f"{y}-{months[m.capitalize()]}-{d.zfill(2)}"
        except Exception:
            return None
