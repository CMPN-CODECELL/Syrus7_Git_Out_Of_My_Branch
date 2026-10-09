"""
Instrument master: the daily 021 instruments CSV (~1,05,000 rows), cached on disk and indexed
in memory. Orders must be blocked when the cache is older than today's IST trading date.
"""
import csv
import gzip
import io
import logging
import os
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

from shared.contracts.instruments import Instrument

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
_EPOCH_1980_IST = datetime(1980, 1, 1, tzinfo=IST)

_KNOWN_COLUMNS = tuple(Instrument.model_fields)

_INT_FIELDS = (
    "token", "underlying_token", "min_lot_size", "board_lot_quantity", "freeze_quantity",
    "lower_circuit", "upper_circuit", "expiry", "strike_price", "ticksize",
)


def today_ist(now: Optional[datetime] = None) -> date:
    return (now or datetime.now(timezone.utc)).astimezone(IST).date()


def expiry_to_date(raw: int, *, today: Optional[date] = None) -> Optional[date]:
    """021 says expiry is 'an integer timestamp from the exchange; larger = later'. The encoding
    is not documented, so detect it: YYYYMMDD, Unix seconds/millis, or seconds since 1980 (IST),
    the epoch 021 uses for socket times. A 1980-based value read as Unix lands ~10 years in the
    past, which no listed contract can be, so the past/future test disambiguates."""
    if not raw:
        return None
    today = today or today_ist()
    if 19_000_101 <= raw <= 21_001_231:
        try:
            return date(raw // 10_000, (raw // 100) % 100, raw % 100)
        except ValueError:
            return None
    seconds = raw / 1000 if raw > 10**11 else raw
    as_unix = datetime.fromtimestamp(seconds, tz=IST).date()
    if as_unix >= today - timedelta(days=7):
        return as_unix
    return (_EPOCH_1980_IST + timedelta(seconds=seconds)).date()


def parse_instruments_csv(text: str) -> list[Instrument]:
    rows: list[Instrument] = []
    skipped = 0
    for record in csv.DictReader(io.StringIO(text)):
        try:
            # Keep only known columns so a new column in 021's file cannot break parsing.
            values = {k: (record.get(k) or "").strip() for k in _KNOWN_COLUMNS}
            for field in _INT_FIELDS:
                values[field] = int(float(values.get(field) or 0))
            option_type = values.get("option_type") or None
            values["option_type"] = option_type if option_type in ("CALL", "PUT") else None
            values["board_lot_quantity"] = max(1, values["board_lot_quantity"])
            values["ticksize"] = max(1, values["ticksize"])
            values["symbol"] = values.get("symbol", "").upper()
            rows.append(Instrument.model_validate(values))
        except Exception:
            skipped += 1
    if skipped:
        logger.warning("Skipped %d malformed instrument rows", skipped)
    return rows


class InstrumentStore:
    def __init__(self, instruments: Iterable[Instrument] = (), *, loaded_for: Optional[date] = None):
        self._by_key: dict[tuple[str, int], Instrument] = {}
        self._by_symbol: dict[str, list[Instrument]] = defaultdict(list)
        self._by_isin: dict[str, list[Instrument]] = defaultdict(list)
        self.loaded_for: Optional[date] = None
        self.load(instruments, loaded_for=loaded_for)

    def load(self, instruments: Iterable[Instrument], *, loaded_for: Optional[date]) -> None:
        by_key: dict[tuple[str, int], Instrument] = {}
        by_symbol: dict[str, list[Instrument]] = defaultdict(list)
        by_isin: dict[str, list[Instrument]] = defaultdict(list)
        for inst in instruments:
            by_key[(inst.exchange, inst.token)] = inst
            by_symbol[inst.symbol].append(inst)
            if inst.isin:
                by_isin[inst.isin].append(inst)
        self._by_key, self._by_symbol, self._by_isin = by_key, by_symbol, by_isin
        self.loaded_for = loaded_for

    def __len__(self) -> int:
        return len(self._by_key)

    def is_fresh(self, now: Optional[datetime] = None) -> bool:
        return self.loaded_for is not None and self.loaded_for >= today_ist(now)

    def get(self, exchange: str, token: int) -> Optional[Instrument]:
        return self._by_key.get((exchange, token))

    def get_by_ws(self, ws_code: int, token: int) -> Optional[Instrument]:
        from shared.contracts.instruments import WS_CODE_TO_EXCHANGE
        exchange = WS_CODE_TO_EXCHANGE.get(ws_code)
        return self.get(exchange, token) if exchange else None

    def equity(self, symbol: str, *, prefer: str = "NSECM") -> Optional[Instrument]:
        """Cash-market instrument for a symbol, NSE preferred over BSE."""
        candidates = [i for i in self._by_symbol.get(symbol.upper(), []) if i.exchange in ("NSECM", "BSEEQ")]
        candidates.sort(key=lambda i: 0 if i.exchange == prefer else 1)
        return candidates[0] if candidates else None

    def equity_by_isin(self, isin: str, *, prefer: str = "NSECM") -> Optional[Instrument]:
        candidates = [i for i in self._by_isin.get(isin, []) if i.exchange in ("NSECM", "BSEEQ")]
        candidates.sort(key=lambda i: 0 if i.exchange == prefer else 1)
        return candidates[0] if candidates else None

    def index(self, symbol: str) -> Optional[Instrument]:
        candidates = [i for i in self._by_symbol.get(symbol.upper(), []) if i.is_index]
        candidates.sort(key=lambda i: 0 if i.exchange == "NSEIDX" else 1)
        return candidates[0] if candidates else None

    def options(self, underlying_symbol: str, *, exchange: str = "NSEFO") -> list[Instrument]:
        return [
            i for i in self._by_symbol.get(underlying_symbol.upper(), [])
            if i.exchange == exchange and i.option_type is not None
        ]

    def futures(self, underlying_symbol: str, *, exchange: str = "NSEFO") -> list[Instrument]:
        return [
            i for i in self._by_symbol.get(underlying_symbol.upper(), [])
            if i.exchange == exchange and i.option_type is None and i.instrument_type.startswith("FUT")
        ]

    def option_expiries(self, underlying_symbol: str, *, exchange: str = "NSEFO") -> list[int]:
        return sorted({i.expiry for i in self.options(underlying_symbol, exchange=exchange) if i.expiry})

    def nearest_expiry(self, underlying_symbol: str, *, today: Optional[date] = None, exchange: str = "NSEFO") -> Optional[int]:
        today = today or today_ist()
        for raw in self.option_expiries(underlying_symbol, exchange=exchange):
            expiry_date = expiry_to_date(raw, today=today)
            if expiry_date is not None and expiry_date >= today:
                return raw
        return None

    def search(self, query: str, *, limit: int = 8) -> list[Instrument]:
        """Exact symbol first, then prefix matches, cash and index instruments only."""
        q = query.strip().upper()
        if not q:
            return []
        exact = [i for i in self._by_symbol.get(q, []) if i.exchange in ("NSECM", "BSEEQ", "NSEIDX", "BSEIDX")]
        prefix = [
            i for sym, items in self._by_symbol.items() if sym.startswith(q) and sym != q
            for i in items if i.exchange in ("NSECM", "NSEIDX")
        ]
        seen: set[tuple[str, int]] = set()
        out: list[Instrument] = []
        for inst in exact + sorted(prefix, key=lambda i: (len(i.symbol), i.symbol)):
            key = (inst.exchange, inst.token)
            if key not in seen:
                seen.add(key)
                out.append(inst)
            if len(out) >= limit:
                break
        return out


class InstrumentRepository:
    """Disk cache for the raw gzip CSV, keyed by IST trading date."""

    def __init__(self, path: str):
        self.path = Path(path)

    def _meta_path(self) -> Path:
        return self.path.with_suffix(self.path.suffix + ".date")

    def save(self, csv_bytes: bytes, for_date: date) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with gzip.open(tmp, "wb") as fh:
            fh.write(csv_bytes)
        os.replace(tmp, self.path)
        self._meta_path().write_text(for_date.isoformat(), encoding="utf-8")

    def load(self) -> tuple[Optional[str], Optional[date]]:
        if not self.path.exists():
            return None, None
        try:
            with gzip.open(self.path, "rb") as fh:
                text = fh.read().decode("utf-8", errors="replace")
            meta = self._meta_path()
            loaded_for = date.fromisoformat(meta.read_text(encoding="utf-8").strip()) if meta.exists() else None
            return text, loaded_for
        except Exception as exc:
            logger.warning("Instrument cache unreadable (%s); ignoring", exc)
            return None, None
