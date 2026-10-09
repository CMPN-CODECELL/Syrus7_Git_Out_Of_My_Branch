"""
File Overview: Instrument catalog loader for the Indian stock market.
Downloads, parses, and caches active NSE symbols dynamically on startup, with high-fidelity local fallbacks.
"""

import csv
import logging
import urllib.request
import urllib.error
import threading
from typing import List, Dict

logger = logging.getLogger(__name__)

_NSE_EQUITY_CSV_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
}

# ── Robust Local Fallback List (F&O and highly traded NSE stocks) ──
_FALLBACK_STOCKS = [
    {"symbol": "NIFTY", "name": "Nifty 50 Index", "type": "INDEX"},
    {"symbol": "BANKNIFTY", "name": "Nifty Bank Index", "type": "INDEX"},
    {"symbol": "FINNIFTY", "name": "Nifty Financial Services Index", "type": "INDEX"},
    {"symbol": "RELIANCE", "name": "Reliance Industries Limited", "type": "EQUITY"},
    {"symbol": "TCS", "name": "Tata Consultancy Services Limited", "type": "EQUITY"},
    {"symbol": "HDFCBANK", "name": "HDFC Bank Limited", "type": "EQUITY"},
    {"symbol": "INFY", "name": "Infosys Limited", "type": "EQUITY"},
    {"symbol": "ICICIBANK", "name": "ICICI Bank Limited", "type": "EQUITY"},
    {"symbol": "BHARTIARTL", "name": "Bharti Airtel Limited", "type": "EQUITY"},
    {"symbol": "SBIN", "name": "State Bank of India", "type": "EQUITY"},
    {"symbol": "LICI", "name": "Life Insurance Corporation of India", "type": "EQUITY"},
    {"symbol": "ITC", "name": "ITC Limited", "type": "EQUITY"},
    {"symbol": "HINDUNILVR", "name": "Hindustan Unilever Limited", "type": "EQUITY"},
    {"symbol": "LT", "name": "Larsen & Toubro Limited", "type": "EQUITY"},
    {"symbol": "BAJFINANCE", "name": "Bajaj Finance Limited", "type": "EQUITY"},
    {"symbol": "TATAMOTORS", "name": "Tata Motors Limited", "type": "EQUITY"},
    {"symbol": "M&M", "name": "Mahindra & Mahindra Limited", "type": "EQUITY"},
    {"symbol": "AXISBANK", "name": "Axis Bank Limited", "type": "EQUITY"},
    {"symbol": "SUNPHARMA", "name": "Sun Pharmaceutical Industries Limited", "type": "EQUITY"},
    {"symbol": "ASIANPAINT", "name": "Asian Paints Limited", "type": "EQUITY"},
    {"symbol": "ADANIENT", "name": "Adani Enterprises Limited", "type": "EQUITY"},
    {"symbol": "ADANIPORTS", "name": "Adani Ports and Special Economic Zone Limited", "type": "EQUITY"},
    {"symbol": "KOTAKBANK", "name": "Kotak Mahindra Bank Limited", "type": "EQUITY"},
    {"symbol": "HCLTECH", "name": "HCL Technologies Limited", "type": "EQUITY"},
    {"symbol": "NTPC", "name": "NTPC Limited", "type": "EQUITY"},
    {"symbol": "POWERGRID", "name": "Power Grid Corporation of India Limited", "type": "EQUITY"},
    {"symbol": "TITAN", "name": "Titan Company Limited", "type": "EQUITY"},
    {"symbol": "ULTRACEMCO", "name": "UltraTech Cement Limited", "type": "EQUITY"},
    {"symbol": "TATASTEEL", "name": "Tata Steel Limited", "type": "EQUITY"},
    {"symbol": "JIOFIN", "name": "Jio Financial Services Limited", "type": "EQUITY"},
    {"symbol": "COALINDIA", "name": "Coal India Limited", "type": "EQUITY"},
    {"symbol": "INDUSINDBK", "name": "IndusInd Bank Limited", "type": "EQUITY"},
    {"symbol": "BAJAJFINSV", "name": "Bajaj Finserv Limited", "type": "EQUITY"},
    {"symbol": "BPCL", "name": "Bharat Petroleum Corporation Limited", "type": "EQUITY"},
    {"symbol": "GRASIM", "name": "Grasim Industries Limited", "type": "EQUITY"},
    {"symbol": "JSWSTEEL", "name": "JSW Steel Limited", "type": "EQUITY"},
    {"symbol": "NESTLEIND", "name": "Nestle India Limited", "type": "EQUITY"},
    {"symbol": "TECHM", "name": "Tech Mahindra Limited", "type": "EQUITY"},
    {"symbol": "ONGC", "name": "Oil & Natural Gas Corporation Limited", "type": "EQUITY"},
    {"symbol": "WIPRO", "name": "Wipro Limited", "type": "EQUITY"},
    {"symbol": "HINDALCO", "name": "Hindalco Industries Limited", "type": "EQUITY"},
    {"symbol": "CIPLA", "name": "Cipla Limited", "type": "EQUITY"},
    {"symbol": "DRREDDY", "name": "Dr. Reddy's Laboratories Limited", "type": "EQUITY"},
    {"symbol": "SBILIFE", "name": "SBI Life Insurance Company Limited", "type": "EQUITY"},
    {"symbol": "EICHERMOT", "name": "Eicher Motors Limited", "type": "EQUITY"},
    {"symbol": "HEROMOTOCO", "name": "Hero MotoCorp Limited", "type": "EQUITY"},
    {"symbol": "BRITANNIA", "name": "Britannia Industries Limited", "type": "EQUITY"},
    {"symbol": "APOLLOHOSP", "name": "Apollo Hospitals Enterprise Limited", "type": "EQUITY"},
    {"symbol": "DIVISLAB", "name": "Divi's Laboratories Limited", "type": "EQUITY"},
    {"symbol": "SHRIRAMFIN", "name": "Shriram Finance Limited", "type": "EQUITY"},
    {"symbol": "LTIM", "name": "LTIMindtree Limited", "type": "EQUITY"},
    {"symbol": "BEL", "name": "Bharat Electronics Limited", "type": "EQUITY"},
    {"symbol": "HAL", "name": "Hindustan Aeronautics Limited", "type": "EQUITY"},
    {"symbol": "TRENT", "name": "Trent Limited", "type": "EQUITY"},
    {"symbol": "DLF", "name": "DLF Limited", "type": "EQUITY"},
    {"symbol": "VEDL", "name": "Vedanta Limited", "type": "EQUITY"},
    {"symbol": "ZOMATO", "name": "Zomato Limited", "type": "EQUITY"},
    {"symbol": "IOC", "name": "Indian Oil Corporation Limited", "type": "EQUITY"},
    {"symbol": "GAIL", "name": "GAIL (India) Limited", "type": "EQUITY"},
    {"symbol": "TATACONSUM", "name": "Tata Consumer Products Limited", "type": "EQUITY"},
    {"symbol": "HDFCLIFE", "name": "HDFC Life Insurance Company Limited", "type": "EQUITY"},
    {"symbol": "INDIGO", "name": "InterGlobe Aviation Limited (IndiGo)", "type": "EQUITY"},
    {"symbol": "AMBUJACEM", "name": "Ambuja Cements Limited", "type": "EQUITY"},
    {"symbol": "SIEMENS", "name": "Siemens Limited", "type": "EQUITY"},
    {"symbol": "PNB", "name": "Punjab National Bank", "type": "EQUITY"},
    {"symbol": "CANBK", "name": "Canara Bank", "type": "EQUITY"},
    {"symbol": "TATAELXSI", "name": "Tata Elxsi Limited", "type": "EQUITY"},
    {"symbol": "PIDILITIND", "name": "Pidilite Industries Limited", "type": "EQUITY"},
    {"symbol": "ICICIPRULI", "name": "ICICI Prudential Life Insurance Company Limited", "type": "EQUITY"},
    {"symbol": "GODREJCP", "name": "Godrej Consumer Products Limited", "type": "EQUITY"},
    {"symbol": "DABUR", "name": "Dabur India Limited", "type": "EQUITY"},
    {"symbol": "MARICO", "name": "Marico Limited", "type": "EQUITY"},
    {"symbol": "COLPAL", "name": "Colgate-Palmolive (India) Limited", "type": "EQUITY"},
    {"symbol": "PFC", "name": "Power Finance Corporation Limited", "type": "EQUITY"},
    {"symbol": "RECLTD", "name": "REC Limited", "type": "EQUITY"},
    {"symbol": "SRF", "name": "SRF Limited", "type": "EQUITY"},
    {"symbol": "AUBANK", "name": "AU Small Finance Bank Limited", "type": "EQUITY"},
    {"symbol": "MUTHOOTFIN", "name": "Muthoot Finance Limited", "type": "EQUITY"},
    {"symbol": "POLYCAB", "name": "Polycab India Limited", "type": "EQUITY"},
    {"symbol": "ASHOKLEY", "name": "Ashok Leyland Limited", "type": "EQUITY"},
    {"symbol": "BALKRISIND", "name": "Balkrishna Industries Limited", "type": "EQUITY"},
    {"symbol": "CUMMINSIND", "name": "Cummins India Limited", "type": "EQUITY"},
    {"symbol": "ESCORTS", "name": "Escorts Kubota Limited", "type": "EQUITY"},
    {"symbol": "FEDERALBNK", "name": "The Federal Bank Limited", "type": "EQUITY"},
    {"symbol": "GMRINFRA", "name": "GMR Airports Infrastructure Limited", "type": "EQUITY"},
    {"symbol": "HINDPETRO", "name": "Hindustan Petroleum Corporation Limited", "type": "EQUITY"},
    {"symbol": "IDFCFIRSTB", "name": "IDFC First Bank Limited", "type": "EQUITY"},
    {"symbol": "IRFC", "name": "Indian Railway Finance Corporation Limited", "type": "EQUITY"},
    {"symbol": "LICHSGFIN", "name": "LIC Housing Finance Limited", "type": "EQUITY"},
    {"symbol": "MRF", "name": "MRF Limited", "type": "EQUITY"},
    {"symbol": "NATIONALUM", "name": "National Aluminium Company Limited", "type": "EQUITY"},
    {"symbol": "OBEROIRLTY", "name": "Oberoi Realty Limited", "type": "EQUITY"},
    {"symbol": "PEL", "name": "Piramal Enterprises Limited", "type": "EQUITY"},
    {"symbol": "PETRONET", "name": "Petronet LNG Limited", "type": "EQUITY"},
    {"symbol": "RBLBANK", "name": "RBL Bank Limited", "type": "EQUITY"},
    {"symbol": "SAIL", "name": "Steel Authority of India Limited", "type": "EQUITY"},
    {"symbol": "TATACOMM", "name": "Tata Communications Limited", "type": "EQUITY"},
    {"symbol": "VOLTAS", "name": "Voltas Limited", "type": "EQUITY"},
    {"symbol": "ZEEL", "name": "Zee Entertainment Enterprises Limited", "type": "EQUITY"},
]


class InstrumentsCatalog:
    """Manages the full list of Indian stock market instruments."""

    def __init__(self) -> None:
        self._instruments: List[Dict[str, str]] = []
        self._symbol_set: set = set()  # O(1) lookup cache
        self._lock = threading.Lock()
        self._loaded = False

    def load(self) -> None:
        """Loads symbols on application startup."""
        with self._lock:
            if self._loaded:
                return

            logger.info("Initializing Indian stock market instrument loader...")
            
            # Start with static indices (which aren't listed in the Equity CSV)
            self._instruments = [
                {"symbol": "NIFTY", "name": "Nifty 50 Index", "type": "INDEX"},
                {"symbol": "BANKNIFTY", "name": "Nifty Bank Index", "type": "INDEX"},
                {"symbol": "FINNIFTY", "name": "Nifty Financial Services Index", "type": "INDEX"},
            ]

            try:
                req = urllib.request.Request(_NSE_EQUITY_CSV_URL, headers=_HEADERS)
                # Keep timeout short to prevent long app startup delays
                with urllib.request.urlopen(req, timeout=5) as response:
                    lines = [line.decode("utf-8") for line in response.readlines()]
                    reader = csv.DictReader(lines)
                    
                    added_symbols = set(inst["symbol"] for inst in self._instruments)
                    for row in reader:
                        symbol = row.get("SYMBOL", "").strip().upper()
                        name = row.get("NAME OF COMPANY", "").strip()
                        series = row.get("SERIES", "").strip().upper()
                        
                        if symbol and series == "EQ" and symbol not in added_symbols:
                            self._instruments.append({
                                "symbol": symbol,
                                "name": name,
                                "type": "EQUITY"
                            })
                            added_symbols.add(symbol)
                
                logger.info("Successfully fetched %d active instruments from NSE live archives.", len(self._instruments))
            except Exception as e:
                logger.warning(
                    "NSE Equity CSV download failed or timed out (%s). Using comprehensive local fallback catalog.", e
                )
                # Load fallback stocks
                added_symbols = set(inst["symbol"] for inst in self._instruments)
                for item in _FALLBACK_STOCKS:
                    if item["symbol"] not in added_symbols:
                        self._instruments.append(item)
                        added_symbols.add(item["symbol"])
            
            # If no equities were loaded (e.g. download fetched HTML block page), append fallback catalog
            if len(self._instruments) <= 5:
                logger.warning("Fewer than 5 instruments loaded. Appending comprehensive local fallback catalog.")
                added_symbols = set(inst["symbol"] for inst in self._instruments)
                for item in _FALLBACK_STOCKS:
                    if item["symbol"] not in added_symbols:
                        self._instruments.append(item)
                        added_symbols.add(item["symbol"])

            self._loaded = True
            # Build O(1) lookup set from loaded instruments
            self._symbol_set = {inst["symbol"] for inst in self._instruments}

    def search(self, query: str, limit: int = 15) -> List[Dict[str, str]]:
        """
        Search through instruments in memory.
        If query is empty, returns recommended indices and highly traded stocks.
        """
        if not self._loaded:
            self.load()

        q = query.strip().upper()
        if not q:
            # Return indices and the first few top fallbacks/watchlists
            return self._instruments[:limit]

        # Filter: Match query with symbol or name
        matches = []
        for inst in self._instruments:
            symbol = inst["symbol"]
            name = inst["name"]
            
            # Substring case-insensitive match
            if q in symbol or q in name.upper():
                # Score them so exact/starting matches are prioritized
                score = 0
                if symbol == q:
                    score = 3
                elif symbol.startswith(q):
                    score = 2
                elif q in symbol:
                    score = 1
                
                matches.append((inst, score))

        # Sort matches by score descending, then alphabetically by symbol
        matches.sort(key=lambda x: (-x[1], x[0]["symbol"]))
        
        return [item[0] for item in matches[:limit]]

    def is_valid_symbol(self, symbol: str) -> bool:
        """Quick O(1) check if a symbol is recognized in our catalog."""
        if not self._loaded:
            self.load()
        sym = symbol.strip().upper().replace(".NS", "").replace(".BO", "")
        return sym in self._symbol_set


# Global Singleton Instance
instruments_catalog = InstrumentsCatalog()
