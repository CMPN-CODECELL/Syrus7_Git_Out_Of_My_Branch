"""
One symbol map across the two price sources:
  021 instrument (token, exchange, symbol)  <->  NSE symbol  <->  yfinance ticker

Rule: NSE cash symbols map to "<SYMBOL>.NS", BSE cash to "<SYMBOL>.BO"; indices and known
exceptions come from an explicit table. Anything that cannot be mapped is returned as None so
callers list it as skipped instead of silently dropping it.
"""
import re
from typing import Optional

from shared.contracts.instruments import Instrument

# 021 index symbol -> yfinance ticker
INDEX_TICKERS = {
    "NIFTY": "^NSEI",
    "NIFTY 50": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "NIFTY BANK": "^NSEBANK",
    "FINNIFTY": "NIFTY_FIN_SERVICE.NS",
    "MIDCPNIFTY": "NIFTY_MID_SELECT.NS",
    "NIFTYIT": "^CNXIT",
    "SENSEX": "^BSESN",
    "BANKEX": "BSE-BANK.BO",
}

# 021 cash symbol -> yfinance ticker, where the plain ".NS" rule is wrong.
EQUITY_OVERRIDES: dict[str, str] = {}

_TRADABLE_EQUITY = re.compile(r"^[A-Z0-9&\-]{1,20}$")


def yfinance_ticker(instrument: Instrument) -> Optional[str]:
    symbol = instrument.symbol.upper()
    if instrument.is_index:
        return INDEX_TICKERS.get(symbol)
    if instrument.exchange not in ("NSECM", "BSEEQ"):
        return None  # derivatives have no usable daily history; use the underlying
    if symbol in EQUITY_OVERRIDES:
        return EQUITY_OVERRIDES[symbol]
    if not _TRADABLE_EQUITY.match(symbol):
        return None
    return f"{symbol}.NS" if instrument.exchange == "NSECM" else f"{symbol}.BO"


def analysis_key(instrument: Instrument) -> str:
    """Key used for OHLC storage: the 021 symbol, suffixed for BSE-only listings."""
    return instrument.symbol.upper() if instrument.exchange != "BSEEQ" else f"{instrument.symbol.upper()}.BO"
