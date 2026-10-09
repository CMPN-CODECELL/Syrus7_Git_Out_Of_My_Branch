"""
File Overview: FastAPI router endpoint for downloading multi-day research EOD Excel workbooks.

Endpoints/APIs:
- GET /v1/export/research-eod: Download custom multi-day Excel workbook.
"""

from datetime import datetime, date
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Response
import logging

from shared.utils.symbol_validator import SymbolValidator
from domains.analytics.application.historical_research_exporter import generate_research_excel_workbook

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/export", tags=["export"])


@router.get("/research-eod")
async def export_research_eod(
    symbol: str = Query(..., description="Ticker symbol (e.g., NIFTY, IREDA, RELIANCE)"),
    start_date: str = Query(..., description="Start date in YYYY-MM-DD format"),
    end_date: str = Query(..., description="End date in YYYY-MM-DD format"),
    layout_mode: str = Query("separate_tabs", description="Layout: 'separate_tabs' (2 tabs per day) or 'combined_per_day' (1 sheet per day)"),
):
    """
    Download an Excel workbook for custom historical date period.
    Generates 1 sheet per day (or 2 tabs per day: Option Chain + Technicals)
    with exact screenshot styling.
    """
    symbol_upper = symbol.strip().upper()
    is_valid = SymbolValidator.validate(symbol_upper)
    if not is_valid:
        raise HTTPException(status_code=400, detail=f"Symbol '{symbol_upper}' is invalid or not supported.")

    symbol_clean = SymbolValidator.get_clean_symbol(symbol_upper)

    try:
        dt_start = datetime.strptime(start_date, "%Y-%m-%d").date()
        dt_end = datetime.strptime(end_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="Invalid date format. Please provide start_date and end_date in YYYY-MM-DD format (e.g. 2026-08-01)."
        )

    if dt_start > dt_end:
        raise HTTPException(status_code=400, detail="start_date must be less than or equal to end_date.")

    if (dt_end - dt_start).days > 90:
        raise HTTPException(status_code=400, detail="Maximum export date range is 90 days per request.")

    try:
        excel_bytes = generate_research_excel_workbook(
            symbol=symbol_clean,
            start_date=dt_start,
            end_date=dt_end,
            layout_mode=layout_mode
        )

        filename = f"AlphaStreams_{symbol_clean}_{dt_start.strftime('%Y%m%d')}_to_{dt_end.strftime('%Y%m%d')}.xlsx"
        
        return Response(
            content=excel_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Access-Control-Expose-Headers": "Content-Disposition"
            }
        )
    except Exception as exc:
        logger.error("[%s] Error generating research Excel export: %s", symbol_clean, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to generate research Excel file: {str(exc)}")
