"""
Tool catalogue for the LLM. Each tool has a strict argument model (unknown keys are rejected)
and a JSON-schema declaration for function calling.

Read tools return facts. Draft tools (Level 2) only create a proposal card for the trader to
approve or reject. There is deliberately no tool that sends, approves, modifies or cancels an
order at the broker.
"""
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from shared.contracts.orders import OrderChangeDraft, OrderDraft


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


# ── Draft tools (Level 2): create a proposal card; never send ──

DRAFT_TOOL_ARG_MODELS: dict[str, type[BaseModel]] = {
    "draft_order": OrderDraft,
    "draft_modify_order": OrderChangeDraft,
    "draft_cancel_order": OrderChangeDraft,
}

_PRICE_TEXT = "Exactly as the trader wrote it, e.g. '2800', '₹2,800.50', '2.8k'. Do not convert units."

_CHANGE_PROPS = {
    "symbol_query": {"type": "STRING", "description": "Symbol or name of the order's instrument, e.g. HDFCBANK"},
    "side": {"type": "STRING", "enum": ["BUY", "SELL"], "description": "Only if the trader said which side"},
    "stop_loss_only": {"type": "BOOLEAN", "description": "True when the trader refers to their stop-loss order"},
    "order_id": {"type": "STRING", "description": "Only if the trader gave or picked an order number"},
}

DRAFT_TOOL_DECLARATIONS: list[dict] = [
    {
        "name": "draft_order",
        "description": ("Prepare a NEW order as a confirmation card for the trader to approve. Does not send anything. "
                        "Use only for explicit instructions to buy or sell, never for hypotheticals. Leave quantity empty "
                        "if the trader did not give one; Kraken will ask."),
        "parameters": _obj({
            "action": {"type": "STRING", "enum": ["BUY", "SELL"]},
            "symbol_query": {"type": "STRING", "description": "Symbol or company name; for F&O the underlying, e.g. NIFTY"},
            "quantity": {"type": "INTEGER", "description": "Shares, or lots when quantity_mode is LOTS. Omit if not stated."},
            "quantity_mode": {"type": "STRING", "enum": ["UNITS", "LOTS", "HALF", "ALL"],
                              "description": "HALF/ALL = half/all of the current holding or position"},
            "order_type": {"type": "STRING", "enum": ["MARKET", "LIMIT", "SL"]},
            "limit_price": {"type": "STRING", "description": _PRICE_TEXT},
            "trigger_price": {"type": "STRING", "description": "Stop-loss trigger. " + _PRICE_TEXT},
            "product": {"type": "STRING", "enum": ["CNC", "INTRADAY", "NRML"], "description": "Only if the trader said so"},
            "exchange_hint": {"type": "STRING", "enum": ["NSE", "BSE"], "description": "Only if the trader named BSE/NSE"},
            "validity": {"type": "STRING", "enum": ["Day", "IOC"]},
            "instrument_kind": {"type": "STRING", "enum": ["EQUITY", "OPTION", "FUTURE"]},
            "expiry": {"type": "STRING", "description": "Trader's words, e.g. 'this expiry', 'next', '28 Oct'"},
            "strike": {"type": "STRING", "description": "Option strike as written, e.g. '24500'"},
            "option_type": {"type": "STRING", "enum": ["CE", "PE"]},
            "source": {"type": "STRING", "enum": ["HOLDING", "POSITION"], "description": "Only to answer which one to sell from"},
            "short": {"type": "BOOLEAN", "description": "True only if the trader explicitly asked to short-sell"},
        }, ["action", "symbol_query"]),
    },
    {
        "name": "draft_modify_order",
        "description": "Prepare a change to one OPEN order (price, stop-loss trigger or quantity) as a confirmation card. Does not send anything.",
        "parameters": _obj({
            **_CHANGE_PROPS,
            "new_limit_price": {"type": "STRING", "description": _PRICE_TEXT},
            "new_trigger_price": {"type": "STRING", "description": _PRICE_TEXT},
            "new_quantity": {"type": "INTEGER"},
        }, ["symbol_query"]),
    },
    {
        "name": "draft_cancel_order",
        "description": "Prepare cancellation of one OPEN order as a confirmation card. Does not send anything.",
        "parameters": _obj(dict(_CHANGE_PROPS), ["symbol_query"]),
    },
]
