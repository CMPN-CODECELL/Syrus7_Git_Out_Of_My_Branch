"""
File Overview: Factory function to return the analysis market data adapter (yfinance + NSE scraper).
Orders, P&L and price triggers never use this adapter; they use the 021 broker domain.
"""

import logging

logger = logging.getLogger(__name__)


def get_market_data_adapter(redis_client=None):
    """
    Returns the analysis-feed adapter. Only the NSE/yfinance adapter ships with Kraken.
    redis_client is accepted for call-site compatibility.
    """
    from domains.ingestion.infrastructure.outbound.nse_api_adapter import NseApiAdapter
    logger.debug("Initializing NseApiAdapter (yfinance/NSE) as the analysis data provider.")
    return NseApiAdapter()
