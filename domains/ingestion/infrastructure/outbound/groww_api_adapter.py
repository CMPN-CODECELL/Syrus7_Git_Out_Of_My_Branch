"""
File Overview: Outbound adapter for Groww API. Handles market price and option chain retrieval.
Includes automated fallback to yfinance and NSE API if Groww credentials are not active.
"""

import logging
import asyncio
import aiohttp
from datetime import datetime, timezone
from typing import Optional, List

from domains.ingestion.ports.interface.outbound.i_market_price_source_port import IMarketPriceSourcePort
from domains.ingestion.ports.interface.outbound.i_option_chain_source_port import IOptionChainSourcePort
from domains.ingestion.application.dto.raw_tick_dto import RawTickDTO
from domains.ingestion.infrastructure.outbound.nse_api_adapter import NseApiAdapter

logger = logging.getLogger(__name__)

try:
    from growwapi import GrowwAPI
    GROWW_SDK_AVAILABLE = True
except ImportError:
    GROWW_SDK_AVAILABLE = False


class GrowwApiAdapter(IMarketPriceSourcePort, IOptionChainSourcePort):
    """
    Adapter for market data via Groww API with a fallback to NseApiAdapter (yfinance/NSE proxy).
    """

    def __init__(
        self,
        api_key: str = "",
        secret_key: str = "",
        access_token: str = "",
        totp_secret: str = "",
        pin: str = "",
        redis_client=None,
    ) -> None:
        self.api_key = api_key
        self.secret_key = secret_key
        self._access_token = access_token
        self.totp_secret = totp_secret
        self.pin = pin
        self._session: Optional[aiohttp.ClientSession] = None
        self._fallback_adapter = NseApiAdapter()
        self._redis = redis_client

    async def _ensure_session(self) -> aiohttp.ClientSession:
        current_loop = asyncio.get_running_loop()
        if self._session is not None and not self._session.closed:
            if getattr(self._session, "_loop", None) is not current_loop:
                try:
                    await self._session.close()
                except Exception:
                    pass
                self._session = None

        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=8, connect=3),
                connector=aiohttp.TCPConnector(
                    limit=20,
                    keepalive_timeout=60,
                    enable_cleanup_closed=True,
                ),
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        await self._fallback_adapter.close()

    async def _get_headers(self) -> dict:
        token = await self._get_token()
        headers = {
            "Accept": "application/json",
            "X-API-VERSION": "1.0",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    async def _get_token(self) -> Optional[str]:
        if self._access_token:
            if not self._is_token_expired(self._access_token):
                return self._access_token
            logger.info("Access token in settings is expired. Cleared to refresh dynamically.")
            self._access_token = ""

        if (self.totp_secret or (self.api_key and self.secret_key)) and GROWW_SDK_AVAILABLE:
            try:
                loop = asyncio.get_running_loop()
                token = await loop.run_in_executor(
                    None,
                    self._fetch_token_sync
                )
                if token:
                    self._access_token = token
                    logger.info("Successfully retrieved daily Groww API Access Token.")
                    try:
                        import base64
                        import json
                        parts = token.split('.')
                        if len(parts) == 3:
                            payload_b64 = parts[1]
                            payload_b64 += '=' * (4 - len(payload_b64) % 4)
                            payload = json.loads(base64.b64decode(payload_b64).decode('utf-8'))
                            sub_payload = json.loads(payload.get('sub', '{}'))
                            roles = sub_payload.get('role', '')
                            if 'live_data-basic' not in roles:
                                logger.warning("Dynamically generated token lacks 'live_data-basic' role (roles: %s). Groww API requests may fail with 403 Forbidden. Manually set a valid GROWW_ACCESS_TOKEN in .env if live options data is needed.", roles)
                    except Exception:
                        pass
                    return token
            except Exception as e:
                logger.error("Failed to generate Groww access token dynamically: %s", e)

        return None

    def _is_token_expired(self, token: str) -> bool:
        import base64
        import json
        import time
        try:
            parts = token.split('.')
            if len(parts) != 3:
                # Mock token or generic API token in tests; treat as not expired
                return False
            payload_b64 = parts[1]
            payload_b64 += '=' * (4 - len(payload_b64) % 4)
            payload_json = base64.b64decode(payload_b64).decode('utf-8')
            payload = json.loads(payload_json)
            exp = payload.get('exp')
            if exp:
                return time.time() > float(exp)
        except Exception:
            pass
        return True

    def _fetch_token_sync(self) -> Optional[str]:
        try:
            totp_code = None
            if self.totp_secret:
                try:
                    import pyotp
                    totp = pyotp.TOTP(self.totp_secret.replace(" ", "").upper())
                    totp_code = totp.now()
                except Exception as e:
                    logger.warning("TOTP generation failed: %s", e)

            # Try SDK methods with available parameters
            if totp_code:
                # Attempt 1: GrowwAPI SDK get_access_token with totp
                try:
                    return GrowwAPI.get_access_token(
                        api_key=self.api_key or self.totp_secret,
                        totp=totp_code,
                        pin=self.pin
                    )
                except (TypeError, AttributeError):
                    pass
                
                # Attempt 2: Standard GrowwAPI SDK (key + totp as secret)
                try:
                    return GrowwAPI.get_access_token(
                        api_key=self.api_key,
                        secret=totp_code
                    )
                except Exception:
                    pass

            # Fallback to key + secret_key if present
            if self.api_key and self.secret_key:
                return GrowwAPI.get_access_token(api_key=self.api_key, secret=self.secret_key)

        except Exception as e:
            logger.error("Error in GrowwAPI token retrieval: %s", e)
        return None

    # ── Market Price (Groww API) ─────────────────────────────────

    async def fetch_price(self, symbol: str) -> Optional[dict]:
        """Fetches latest price info from Groww. Falls back to yfinance on failure."""
        token = await self._get_token()
        if not token:
            logger.debug("[%s] No Groww access token. Falling back to yfinance.", symbol)
            return await self._fallback_adapter.fetch_price(symbol)

        clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "")
        # Always use CASH segment for quote queries on Groww (both stocks and indices)
        segment = "CASH"

        url = "https://api.groww.in/v1/live-data/quote"
        params = {
            "exchange": "NSE",
            "segment": segment,
            "trading_symbol": clean_sym
        }

        try:
            session = await self._ensure_session()
            headers = await self._get_headers()
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("status") == "SUCCESS" and "payload" in data:
                        payload = data["payload"]
                        ohlc = payload.get("ohlc", {})
                        
                        last_price = payload.get("last_price") or payload.get("lastPrice") or 0.0
                        open_p = ohlc.get("open") or payload.get("open") or last_price
                        high_p = ohlc.get("high") or payload.get("high") or last_price
                        low_p = ohlc.get("low") or payload.get("low") or last_price
                        close_p = ohlc.get("close") or payload.get("close") or last_price
                        volume = payload.get("volume") or 0
                        change_percent = payload.get("day_change_perc") or payload.get("dayChangePerc") or 0.0
                        
                        # Dividend yield: check Redis cache first, fallback to yfinance only on miss
                        dividend_yield = 0.0
                        div_key = f"market:dividend_yield:{symbol.upper()}"
                        try:
                            cached_div = await self._redis.get(div_key) if self._redis else None
                            if cached_div is not None:
                                dividend_yield = float(cached_div)
                            else:
                                yf_info = await self._fallback_adapter.fetch_price(symbol)
                                if yf_info:
                                    dividend_yield = yf_info.get("dividend_yield", 0.0)
                                if self._redis:
                                    await self._redis.setex(div_key, 86400, str(dividend_yield))
                        except Exception:
                            pass

                        return {
                            "symbol": symbol.upper(),
                            "last_price": round(float(last_price), 2),
                            "open": round(float(open_p), 2),
                            "high": round(float(high_p), 2),
                            "low": round(float(open_p), 2) if open_p < low_p else round(float(low_p), 2),
                            "volume": int(volume),
                            "previous_close": round(float(close_p), 2),
                            "change_percent": round(float(change_percent), 2),
                            "currency": "INR",
                            "dividend_yield": float(dividend_yield),
                            "last_updated": datetime.now(timezone.utc).isoformat(),
                        }
                    else:
                        logger.debug("[%s] Groww API returned status: %s. Falling back to yfinance.", symbol, data.get("status"))
                else:
                    logger.debug("[%s] Groww API quote request failed (status %d). Falling back to yfinance.", symbol, resp.status)
        except Exception as e:
            logger.debug("[%s] Groww API quote fetch exception: %s. Falling back to yfinance.", symbol, e)

        return await self._fallback_adapter.fetch_price(symbol)

    # ── Option Chain (Groww API) ───────────────────────────────

    async def fetch_option_chain(self, symbol: str) -> List[RawTickDTO]:
        """Fetches full option chain from Groww. Falls back to NSE proxy/synthetic on failure."""
        token = await self._get_token()
        if not token:
            logger.debug("[%s] No Groww access token. Falling back to NSE option chain.", symbol)
            return await self._fallback_adapter.fetch_option_chain(symbol)

        clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "")

        try:
            # 1. Fetch available expiries from fallback adapter (NSE/yfinance) to bypass the forbidden expiries endpoint
            expiries = []
            try:
                expiries = await self._fallback_adapter.fetch_expiry_dates(symbol)
            except Exception as e:
                logger.warning("[%s] Failed to fetch expiries from fallback adapter: %s", symbol, e)

            # final fallback just in case
            if not expiries:
                expiries_url = "https://api.groww.in/v1/historical/expiries"
                params = {
                    "exchange": "NSE",
                    "underlying_symbol": clean_sym
                }
                session = await self._ensure_session()
                headers = await self._get_headers()
                
                async with session.get(expiries_url, headers=headers, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if isinstance(data, list):
                            expiries = data
                        elif isinstance(data, dict) and "payload" in data:
                            expiries = data["payload"]
                        elif isinstance(data, dict) and "expiries" in data:
                            expiries = data["expiries"]

            if not expiries:
                logger.warning("[%s] No expiries returned. Falling back to NSE option chain.", symbol)
                return await self._fallback_adapter.fetch_option_chain(symbol)

            # Parse and format expiries to YYYY-MM-DD
            formatted_expiries = []
            for exp in expiries:
                if exp.count("-") == 2 and all(part.isdigit() for part in exp.split("-")):
                    formatted_expiries.append(exp)
                else:
                    parsed = NseApiAdapter._parse_nse_date(exp)
                    if parsed:
                        formatted_expiries.append(parsed)

            if not formatted_expiries:
                logger.warning("[%s] No valid expiries after parsing. Falling back.", symbol)
                return await self._fallback_adapter.fetch_option_chain(symbol)

            # Get nearest 2 expiries
            target_expiries = sorted(list(set(formatted_expiries)))[:2]

            dtos = []
            
            # Fetch spot price to attach to ticks
            spot_price = 0.0
            price_data = await self.fetch_price(symbol)
            if price_data:
                spot_price = float(price_data.get("last_price", 0.0))

            session = await self._ensure_session()
            headers = await self._get_headers()

            for expiry in target_expiries:
                chain_url = f"https://api.groww.in/v1/option-chain/exchange/NSE/underlying/{clean_sym}"
                chain_params = {"expiry_date": expiry}
                
                async with session.get(chain_url, headers=headers, params=chain_params) as chain_resp:
                    if chain_resp.status == 200:
                        chain_data = await chain_resp.json()
                        payload = chain_data.get("payload", {})
                        strikes_dict = payload.get("strikes", {})
                        
                        spot_from_payload = payload.get("underlying_ltp")
                        if spot_from_payload:
                            spot_price = float(spot_from_payload)

                        for strike_str, strike_data in strikes_dict.items():
                            try:
                                strike = float(strike_str)
                            except ValueError:
                                continue

                            for opt_type in ["CE", "PE"]:
                                opt_data = strike_data.get(opt_type)
                                if not opt_data or not isinstance(opt_data, dict):
                                    continue
                                
                                ltp = float(opt_data.get("ltp") or 0.0)
                                if ltp <= 0:
                                    continue

                                oi = int(opt_data.get("open_interest") or 0)
                                volume = int(opt_data.get("volume") or 0)
                                
                                greeks = opt_data.get("greeks", {})
                                iv = 0.0
                                if isinstance(greeks, dict):
                                    iv = float(greeks.get("iv") or 0.0)
                                
                                if iv > 1.0:
                                    iv = iv / 100.0

                                dtos.append(RawTickDTO(
                                    symbol=symbol.upper(),
                                    expiry=expiry,
                                    strike=strike,
                                    option_type=opt_type,
                                    oi=oi,
                                    volume=volume,
                                    ltp=ltp,
                                    iv=iv,
                                    underlying_price=spot_price,
                                    timestamp=datetime.now(timezone.utc)
                                ))
                    else:
                        logger.debug("[%s] Groww option chain fetch failed for expiry %s.", symbol, expiry)


            if dtos:
                return dtos
            
            logger.debug("[%s] Groww option chain parsing returned no ticks. Falling back.", symbol)

        except Exception as e:
            logger.error("[%s] Groww option chain fetch exception: %s. Falling back.", symbol, e)

        return await self._fallback_adapter.fetch_option_chain(symbol)
