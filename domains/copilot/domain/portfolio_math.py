"""
Pure portfolio arithmetic in integer paise. No I/O, so every number the copilot reports can be
unit-tested and explained in the viva.

Definitions (stated back to the user in every answer):
- Position unrealized P&L = (LTP - netPrice) x netQuantity          (021 API guide formula)
- Realized today = for each instrument+product, min(bought, sold today) x (avg sell - avg buy),
  from today's trades. Closing quantity carried forward from earlier days is not included.
- Holding day change = (LTP - prevClose) x quantity; holding P&L = (LTP - avg price) x quantity
- "Down X%" = move against you vs average price: (LTP - avg) / avg, sign-flipped for shorts.
"""
from dataclasses import dataclass
from typing import Iterable, Optional

PNL_DEFINITION = "unrealized = (LTP - average price) x open quantity; realized = today's matched buy/sell trades"
MOVE_DEFINITION = "percent move vs your average price, negative = against you (shorts count a rise as down)"


@dataclass(frozen=True)
class PositionPnl:
    exchange: str
    token: int
    symbol: str
    product: str
    net_qty: int
    avg_price: int
    ltp: Optional[int]
    unrealized: Optional[int]
    realized_today: int
    move_pct: Optional[float]
    price_stale: bool


@dataclass(frozen=True)
class HoldingPnl:
    symbol: str
    isin: str
    qty: int
    avg_price: int
    prev_close: int
    ltp: Optional[int]
    pnl: Optional[int]
    day_change: Optional[int]
    move_pct: Optional[float]
    price_stale: bool


def move_pct(avg_price: int, ltp: Optional[int], net_qty: int) -> Optional[float]:
    if ltp is None or avg_price <= 0 or net_qty == 0:
        return None
    raw = (ltp - avg_price) / avg_price * 100.0
    return round(raw if net_qty > 0 else -raw, 2)


def realized_by_key(trades: Iterable[dict]) -> dict[tuple[int, str], int]:
    """(token, product) -> realized paise from today's trades."""
    agg: dict[tuple[int, str], list[int]] = {}
    for t in trades:
        try:
            key = (int(t["token"]), str(t.get("product", "")))
            qty, price = int(t["quantity"]), int(t["price"])
        except (KeyError, TypeError, ValueError):
            continue
        bucket = agg.setdefault(key, [0, 0, 0, 0])  # buy_qty, buy_value, sell_qty, sell_value
        if qty > 0:
            bucket[0] += qty
            bucket[1] += qty * price
        elif qty < 0:
            bucket[2] += -qty
            bucket[3] += -qty * price
    out: dict[tuple[int, str], int] = {}
    for key, (bq, bv, sq, sv) in agg.items():
        matched = min(bq, sq)
        if matched:
            out[key] = round(matched * (sv / sq - bv / bq))
    return out


def position_pnl(position: dict, ltp: Optional[int], realized: int, symbol: str, price_stale: bool) -> PositionPnl:
    net_qty = int(position.get("netQuantity", 0) or 0)
    avg = int(position.get("netPrice", 0) or 0)
    unrealized = (ltp - avg) * net_qty if (ltp is not None and net_qty) else (0 if net_qty == 0 else None)
    return PositionPnl(
        exchange=str(position.get("exchange", "")),
        token=int(position.get("token", 0) or 0),
        symbol=symbol,
        product=str(position.get("product", "")),
        net_qty=net_qty,
        avg_price=avg,
        ltp=ltp,
        unrealized=unrealized,
        realized_today=realized,
        move_pct=move_pct(avg, ltp, net_qty),
        price_stale=price_stale,
    )


def holding_qty(holding: dict) -> int:
    return int(holding.get("freeQty", 0) or 0) + int(holding.get("btstQty", 0) or 0)


def holding_pnl(holding: dict, ltp: Optional[int], price_stale: bool) -> HoldingPnl:
    qty = holding_qty(holding)
    avg = int(holding.get("price", 0) or 0)
    prev = int(holding.get("prevClose", 0) or 0)
    return HoldingPnl(
        symbol=str(holding.get("symbol", "")),
        isin=str(holding.get("isin", "")),
        qty=qty,
        avg_price=avg,
        prev_close=prev,
        ltp=ltp,
        pnl=(ltp - avg) * qty if ltp is not None else None,
        day_change=(ltp - prev) * qty if (ltp is not None and prev) else None,
        move_pct=move_pct(avg, ltp, qty),
        price_stale=price_stale,
    )


def rupees(paise: Optional[int]) -> Optional[str]:
    """Display helper for tool output (the UI may re-format). Indian grouping, 2 decimals."""
    if paise is None:
        return None
    sign = "-" if paise < 0 else ""
    whole, frac = divmod(abs(paise), 100)
    digits = str(whole)
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join(groups + [tail])
    return f"{sign}Rs {digits}.{frac:02d}"
