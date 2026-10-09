"""
File Overview: FastAPI router for the /v1/symbols endpoint, providing a list of recommended symbols from application settings.

All Functions/Classes:
- GetSymbols: FastAPI GET endpoint. Take default symbols from settings and send SymbolsResponse.

Endpoints/APIs:
- GET /symbols.

Database Tables:
- None.
"""
# app/domain/api/routers/symbols.py — GET /v1/symbols endpoint


from fastapi import APIRouter, Query

from app.config import get_settings
from domains.analytics.api.schemas import SymbolsResponse, SymbolSearchResponse, SymbolSearchItem
from domains.analytics.api.instruments_loader import instruments_catalog

router = APIRouter()


@router.get("/symbols", response_model=SymbolsResponse)
async def GetSymbols():
    """
    Returns the list of recommended stock symbols.
    Frontend uses this to populate the default symbol dropdown.
    """
    cfg = get_settings()
    symbols = cfg.get_default_symbols_as_list()
    return SymbolsResponse(
        symbols=symbols,
        count=len(symbols),
        generated_at="",
        source="settings_defaults",
        stale=False,
        partial=False,
    )


@router.get("/symbols/search", response_model=SymbolSearchResponse)
async def GetSymbolsSearch(q: str = Query("", description="Query prefix or substring to search for instruments")):
    """
    Case-insensitive search over all Indian stock market instruments.
    Returns matching stock tickers and indices with names and asset type.
    """
    results = instruments_catalog.search(q, limit=15)
    items = [
        SymbolSearchItem(
            symbol=item["symbol"],
            name=item["name"],
            type=item["type"]
        )
        for item in results
    ]
    return SymbolSearchResponse(
        results=items,
        count=len(items),
        generated_at="",
        source="dynamic_instruments_catalog",
        stale=False,
        partial=False,
    )

