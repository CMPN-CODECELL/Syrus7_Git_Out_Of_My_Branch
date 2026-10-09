"""
File Overview: Utility for validating and formatting Indian stock market ticker symbols (NSE/BSE).

All Functions/Classes:
- SymbolValidator (class): Provides static methods to validate symbols and clean them with Indian suffixes (.NS/.BO). Data: Symbol String -> Boolean/Cleaned Symbol.

Endpoints/APIs:
- External: yfinance API for ticker verification.

Database Tables:
- None.
"""
import logging

import yfinance as yf
from functools import lru_cache

logger = logging.getLogger(__name__)

class SymbolValidator:
    """
    Utility to validate if a ticker symbol exists and is supported.
    Strictly limits validation to the Indian stock market (NSE/BSE).
    Uses local mapping for speed, yfinance for fallback verification.
    """

    _LOCAL_NSE_MAP = {
        "NIFTY": "NIFTY",
        "BANKNIFTY": "BANKNIFTY",
        "FINNIFTY": "FINNIFTY",
        "RELIANCE": "RELIANCE.NS",
        "TCS": "TCS.NS",
        "INFY": "INFY.NS",
        "HDFCBANK": "HDFCBANK.NS",
        "ICICIBANK": "ICICIBANK.NS",
        "BHARTIARTL": "BHARTIARTL.NS",
        "SBIN": "SBIN.NS",
        "LICI": "LICI.NS",
        "ITC": "ITC.NS",
        "HINDUNILVR": "HINDUNILVR.NS",
        "LT": "LT.NS",
        "BAJFINANCE": "BAJFINANCE.NS"
    }

    @staticmethod
    @lru_cache(maxsize=1000)
    def validate(symbol: str) -> bool:
        """
        Check if a symbol is valid and from the Indian market.
        Valid formats: Ticker.NS, Ticker.BO, or INDEX_SYMBOLS.
        """
        if not symbol:
            return False
            
        symbol_upper = symbol.strip().upper()
        
        # 0. Allow known indices
        from shared.constants import INDEX_SYMBOLS
        if symbol_upper in INDEX_SYMBOLS or "^" in symbol_upper:
            return True

        # 0.5 Check local map
        if symbol_upper in SymbolValidator._LOCAL_NSE_MAP:
            return True

        # 0.6 Check dynamic instruments catalog
        try:
            from domains.analytics.api.instruments_loader import instruments_catalog
            if instruments_catalog.is_valid_symbol(symbol_upper):
                return True
        except Exception:
            pass

        # 1. Check if it's already an Indian market symbol
        if symbol_upper.endswith(".NS") or symbol_upper.endswith(".BO"):
            try:
                ticker = yf.Ticker(symbol_upper)
                hist = ticker.history(period="1d")
                if not hist.empty:
                    return True
            except Exception:
                pass
            return False

        # 2. Heuristic for Indian stocks: If no suffix, try .NS then .BO
        if symbol_upper.isalnum():
            # Try NSE first (default)
            try:
                ticker = yf.Ticker(f"{symbol_upper}.NS")
                hist = ticker.history(period="1d")
                if not hist.empty:
                    return True
            except Exception:
                pass
                
            # Try BSE
            try:
                ticker = yf.Ticker(f"{symbol_upper}.BO")
                hist = ticker.history(period="1d")
                if not hist.empty:
                    return True
            except Exception:
                pass
                
        # 3. Reject everything else (foreign stocks, etc.)
        return False

    @staticmethod
    @lru_cache(maxsize=2000)
    def get_clean_symbol(symbol: str) -> str:
        """
        Returns the Indian market formatted version of the symbol (e.g., adding .NS).
        """
        if not symbol:
            return ""
            
        symbol_upper = symbol.strip().upper()
        
        # 0. Already has correct suffix or is an index
        from shared.constants import INDEX_SYMBOLS
        if symbol_upper.endswith(".NS") or symbol_upper.endswith(".BO") or symbol_upper in INDEX_SYMBOLS or "^" in symbol_upper:
            return symbol_upper
            
        # 0.5 Check local map (Fastest)
        if symbol_upper in SymbolValidator._LOCAL_NSE_MAP:
            return SymbolValidator._LOCAL_NSE_MAP[symbol_upper]

        # 0.6 Check dynamic instruments catalog
        try:
            from domains.analytics.api.instruments_loader import instruments_catalog
            if instruments_catalog.is_valid_symbol(symbol_upper):
                from shared.constants import INDEX_SYMBOLS
                if symbol_upper not in INDEX_SYMBOLS:
                    return f"{symbol_upper}.NS"
                return symbol_upper
        except Exception:
            pass
            
        # 1. Try to resolve bare symbol to Indian market (Slow fallback)
        if symbol_upper.isalnum():
            # Try NSE
            try:
                ticker = yf.Ticker(f"{symbol_upper}.NS")
                hist = ticker.history(period="1d")
                if not hist.empty:
                    return f"{symbol_upper}.NS"
            except Exception:
                pass
                
            # Try BSE
            try:
                ticker = yf.Ticker(f"{symbol_upper}.BO")
                hist = ticker.history(period="1d")
                if not hist.empty:
                    return f"{symbol_upper}.BO"
            except Exception:
                pass
            
        return symbol_upper
