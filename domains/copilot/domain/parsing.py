"""
Deterministic parsing of the trader's words into exact values. The LLM passes raw text
("₹2,800.50", "2.8k", "28 Oct"); this module turns it into paise and dates, or refuses.
"""
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

_MULTIPLIERS = {"k": Decimal(1_000), "l": Decimal(100_000), "lakh": Decimal(100_000), "lac": Decimal(100_000),
                "cr": Decimal(10_000_000), "crore": Decimal(10_000_000)}
_PRICE_RE = re.compile(r"^([0-9]*\.?[0-9]+)\s*(k|l|lakh|lac|cr|crore)?$")
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


class ParseError(ValueError):
    """The text cannot be turned into an exact value; the message is shown to the trader."""


def parse_price_paise(text: str) -> int:
    """'₹2,800.50' -> 280050, '2.8k' -> 280000, 'Rs 1,40,000' -> 14000000. Refuses anything inexact."""
    if text is None:
        raise ParseError("No price given.")
    raw = str(text).strip().lower()
    cleaned = raw.replace("₹", "").replace("inr", "").replace(",", "").replace(" ", "")
    cleaned = re.sub(r"^rs\.?", "", cleaned)
    if cleaned.startswith("-"):
        raise ParseError(f"Price '{text}' is negative.")
    match = _PRICE_RE.match(cleaned)
    if not match:
        raise ParseError(f"I couldn't read '{text}' as a price.")
    try:
        value = Decimal(match.group(1)) * _MULTIPLIERS.get(match.group(2) or "", Decimal(1))
    except InvalidOperation as exc:
        raise ParseError(f"I couldn't read '{text}' as a price.") from exc
    paise = value * 100
    if paise != paise.to_integral_value():
        raise ParseError(f"Price '{text}' has more precision than 1 paisa.")
    if paise <= 0:
        raise ParseError(f"Price '{text}' must be greater than zero.")
    return int(paise)


def round_to_tick(paise: int, tick: int, side: str) -> int:
    """Round to the instrument's tick in the trader's favour: buys round down, sells round up."""
    if tick <= 1 or paise % tick == 0:
        return paise
    down = paise - paise % tick
    rounded = down if side == "BUY" else down + tick
    if rounded <= 0:
        raise ParseError("Price rounds to zero at this instrument's tick size.")
    return rounded


def resolve_expiry(text: Optional[str], available: list[date], today: date) -> date:
    """Pick an expiry from `available` (sorted) for phrases like 'this', 'next', '28 Oct',
    '2026-10-28' or 'Oct' (= last expiry of that month). Only dates on or after today count."""
    upcoming = sorted(d for d in available if d >= today)
    if not upcoming:
        raise ParseError("No upcoming expiry is listed for this contract.")
    phrase = (text or "").strip().lower()
    if phrase in ("", "this", "current", "nearest", "this expiry", "this week", "weekly", "near"):
        return upcoming[0]
    if phrase in ("next", "next expiry", "next week"):
        if len(upcoming) < 2:
            raise ParseError("Only one upcoming expiry is listed.")
        return upcoming[1]

    try:
        wanted = date.fromisoformat(phrase)
    except ValueError:
        wanted = None
    if wanted is None:
        tokens = re.findall(r"[a-z]+|\d+", phrase)
        day = next((int(t) for t in tokens if t.isdigit() and int(t) <= 31), None)
        month = next((_MONTHS[t[:3]] for t in tokens if t[:3] in _MONTHS), None)
        year = next((int(t) for t in tokens if t.isdigit() and len(t) == 4), None)
        if month is None:
            raise ParseError(f"I couldn't read '{text}' as an expiry.")
        candidates = [d for d in upcoming if d.month == month and (year is None or d.year == year)]
        if day is None:
            if not candidates:
                raise ParseError(f"No listed expiry in {text}.")
            return candidates[-1]  # monthly expiry = last one in the month
        wanted = next((d for d in candidates if d.day == day), None)
        if wanted is None:
            raise ParseError(f"No listed expiry on {text}. Next expiries: {', '.join(d.isoformat() for d in upcoming[:4])}.")
        return wanted
    if wanted not in upcoming:
        raise ParseError(f"{wanted.isoformat()} is not a listed upcoming expiry. Next expiries: {', '.join(d.isoformat() for d in upcoming[:4])}.")
    return wanted
