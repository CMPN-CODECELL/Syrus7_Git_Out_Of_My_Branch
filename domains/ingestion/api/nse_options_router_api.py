"""
File Overview: Inbound API adapter for fetching live NSE option chains.
Used by background ingestion workers to bypass WAF.

All Functions/Classes:
- lifespan: Manages httpx client lifecycle. Data: App startup -> client init -> shutdown close.
- refresh_nse_cookies: Session manager. Data: NSE homepage -> updated cookie jar.
- get_option_chain: Live fetcher. Data: symbol/index-flag -> raw NSE records.

Endpoints/APIs: GET /options/{symbol}

Database Tables: None (Direct NSE API proxy)
"""
from fastapi import APIRouter, HTTPException
from typing import Dict, Any
from urllib.parse import quote
import httpx
import asyncio
import logging

from shared.constants import INDEX_SYMBOLS

logger = logging.getLogger("nse_options_router")

# Constants for NSE API
NSE_BASE_URL = "https://www.nseindia.com"
INDICES_API_URL = "https://www.nseindia.com/api/option-chain-indices?symbol="
EQUITIES_API_URL = "https://www.nseindia.com/api/option-chain-equities?symbol="

# Standard browser headers to prevent getting blocked
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive"
}

# Global client to maintain connection pools and cookies across requests
client: httpx.AsyncClient = None


async def startup_nse_client() -> None:
    """Initialize the NSE httpx client. Called from main app lifespan."""
    global client
    client = httpx.AsyncClient(headers=HEADERS, timeout=20.0, follow_redirects=True)
    try:
        await refresh_nse_cookies()
    except Exception as e:
        logger.error("Initial cookie refresh failed: %s", e)


async def shutdown_nse_client() -> None:
    """Close the NSE httpx client. Called from main app lifespan."""
    global client
    if client:
        await client.aclose()
        client = None


# Single router instance (lifespan managed by main app, not this sub-router)
nse_options_router_api = APIRouter()


async def refresh_nse_cookies(symbol: str = "NIFTY"):
    """Hits the NSE homepage and option-chain page to generate fresh session cookies."""
    global client
    if client is None:
        client = httpx.AsyncClient(headers=HEADERS, timeout=20.0, follow_redirects=True)
    try:
        client.cookies.clear()
        # 1. Base URL
        await client.get(NSE_BASE_URL)
        await asyncio.sleep(1.0)
 
        # 2. Option Chain Page (Critical for session state)
        clean_name = symbol.upper().replace(".NS", "").replace(".BO", "")
        url = f"https://www.nseindia.com/option-chain?symbol={clean_name}"
        await client.get(url)
        await asyncio.sleep(1.0)
 
        # 3. Soften with master-quote
        await client.get(f"{NSE_BASE_URL}/api/master-quote", headers=HEADERS)
 
        logger.info("[%s] NSE Cookies refreshed successfully", clean_name)
    except Exception as e:
        logger.error("Failed to refresh NSE cookies: %s", e)
 
 
@nse_options_router_api.get("/options/{symbol}", response_model=Dict[str, Any])
async def get_option_chain(symbol: str, is_index: bool = True):
    """
    Fetches the live option chain for a given symbol from NSE.
    """
    # Strip suffixes for NSE
    clean_name = symbol.upper().replace(".NS", "").replace(".BO", "")
    safe_symbol = quote(clean_name)

    # Auto-detect is_index if it seems to be an index
    if clean_name in INDEX_SYMBOLS:
        is_index = True
    elif is_index is True and clean_name not in INDEX_SYMBOLS:
        if "NIFTY" not in clean_name:
            is_index = False

    url = INDICES_API_URL + safe_symbol if is_index else EQUITIES_API_URL + safe_symbol

    global client
    if client is None:
        client = httpx.AsyncClient(headers=HEADERS, timeout=20.0, follow_redirects=True)

    for attempt in range(2):
        try:
            if not client.cookies:
                await refresh_nse_cookies(clean_name)

            response = await client.get(url)

            # Parse response
            data = None
            is_empty = False
            try:
                data = response.json()
                if not data or not isinstance(data, dict) or not data.get('records'):
                    is_empty = True
            except Exception:
                is_empty = True

            if response.status_code in [401, 403] or is_empty:
                logger.warning("[%s] NSE API returned %d or empty, refreshing cookies", clean_name, response.status_code)
                await refresh_nse_cookies(clean_name)
                await asyncio.sleep(1.0)
                response = await client.get(url)
                # Re-parse after retry
                try:
                    data = response.json()
                except Exception:
                    data = None

            response.raise_for_status()

            if data and 'records' in data:
                return {
                    "symbol": symbol.upper(),
                    "timestamp": data['records']['timestamp'],
                    "underlying_value": data['records']['underlyingValue'],
                    "raw_chain": data['records']['data']
                }

        except Exception as e:
            if attempt == 1:
                logger.error("[%s] Final fetch attempt failed: %s", clean_name, e)
                raise HTTPException(status_code=500, detail=f"NSE Fetch Error: {str(e)}")
            await refresh_nse_cookies(clean_name)
            await asyncio.sleep(1.0)

    raise HTTPException(status_code=404, detail="No reliable option records found from NSE")