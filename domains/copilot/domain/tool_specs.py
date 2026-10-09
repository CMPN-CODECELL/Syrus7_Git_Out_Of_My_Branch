"""
Read-only tool catalogue for the LLM. Each tool has a strict argument model (unknown keys are
rejected) and a JSON-schema declaration for function calling. There is deliberately no tool
that can create, send, modify or cancel an order.
"""
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoArgs(_Args):
    pass


class FilterArgs(_Args):
    threshold_pct: float = Field(gt=0, le=100)
    direction: Literal["down", "up"] = "down"
    scope: Literal["positions", "holdings", "both"] = "both"


class SymbolArgs(_Args):
    symbol: str = Field(min_length=1, max_length=40)


class OptionChainArgs(_Args):
    underlying: str = Field("NIFTY", min_length=1, max_length=40)
    strikes_each_side: int = Field(5, ge=1, le=10)


class ScreenArgs(_Args):
    indicator: Literal["RSI14"] = "RSI14"
    op: Literal["below", "above"] = "below"
    value: float = Field(30.0, gt=0, lt=100)


TOOL_ARG_MODELS: dict[str, type[_Args]] = {
    "get_pnl": NoArgs,
    "filter_positions": FilterArgs,
    "get_average_price": SymbolArgs,
    "get_quote": SymbolArgs,
    "option_chain_near_atm": OptionChainArgs,
    "get_technicals": SymbolArgs,
    "screen_portfolio": ScreenArgs,
}


def _obj(properties: dict, required: Optional[list[str]] = None) -> dict:
    return {"type": "OBJECT", "properties": properties, "required": required or []}


TOOL_DECLARATIONS: list[dict] = [
    {
        "name": "get_pnl",
        "description": "Today's P&L: unrealized and realized P&L per open position, plus holdings P&L and day change. All values from 021.",
        "parameters": _obj({}),
    },
    {
        "name": "filter_positions",
        "description": "List positions and/or holdings that moved more than threshold_pct against (down) or for (up) the trader, measured vs average price.",
        "parameters": _obj({
            "threshold_pct": {"type": "NUMBER", "description": "Percent threshold, e.g. 5 for 5%"},
            "direction": {"type": "STRING", "enum": ["down", "up"]},
            "scope": {"type": "STRING", "enum": ["positions", "holdings", "both"]},
        }, ["threshold_pct"]),
    },
    {
        "name": "get_average_price",
        "description": "What the trader paid on average for a symbol: holding average and today's intraday average, reported separately.",
        "parameters": _obj({"symbol": {"type": "STRING", "description": "Trading symbol or company name fragment, e.g. INFY"}}, ["symbol"]),
    },
    {
        "name": "get_quote",
        "description": "Latest 021 price (LTP) for one cash-market symbol or index, with its as-of time.",
        "parameters": _obj({"symbol": {"type": "STRING"}}, ["symbol"]),
    },
    {
        "name": "option_chain_near_atm",
        "description": "Option chain near the money for the nearest expiry on or after today: CE/PE LTP, OI, IV and delta from 021.",
        "parameters": _obj({
            "underlying": {"type": "STRING", "description": "Index or stock, e.g. NIFTY, BANKNIFTY, RELIANCE"},
            "strikes_each_side": {"type": "INTEGER", "description": "Strikes on each side of ATM (1-10, default 5)"},
        }),
    },
    {
        "name": "get_technicals",
        "description": "Daily technical indicators for one symbol (RSI14, SMA50, SMA200, MACD 12/26/9) computed by Kraken's engine on closed daily bars.",
        "parameters": _obj({"symbol": {"type": "STRING"}}, ["symbol"]),
    },
    {
        "name": "screen_portfolio",
        "description": "Screen every holding and open position by an indicator, e.g. RSI14 below 30 (oversold) or above 70 (overbought).",
        "parameters": _obj({
            "indicator": {"type": "STRING", "enum": ["RSI14"]},
            "op": {"type": "STRING", "enum": ["below", "above"]},
            "value": {"type": "NUMBER"},
        }),
    },
]
