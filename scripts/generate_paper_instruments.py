"""
Generate a synthetic instruments file for PAPER_TRADING mode.

The real 021 instruments CSV needs broker credentials. Paper mode only reads instruments from
disk (INSTRUMENTS_CACHE_PATH), so without a file nothing can be searched or ordered. This writes
a small but realistic master: large-cap NSE equities, NIFTY/BANKNIFTY indices, index futures and
option chains whose expiries are computed from today's date.

Usage:  python scripts/generate_paper_instruments.py [output_path]
Re-run when the generated expiries have passed. All prices are in paise.
"""
import gzip
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))

HEADER = ("token,exchange,underlying_token,underlying_exchange,min_lot_size,board_lot_quantity,freeze_quantity,"
          "lower_circuit,upper_circuit,expiry,option_type,strike_price,symbol,instrument_type,isin,ticksize")

# symbol: (NSE token, ISIN, reference price in paise). Tokens/prices of the first six match the
# PaperBroker / PaperMarketSocket seeds so holdings and live ticks line up with these rows.
EQUITIES = {
    "RELIANCE":   (2885,  "INE002A01018", 281000),
    "INFY":       (1594,  "INE009A01021", 153500),
    "TCS":        (11536, "INE467B01029", 348000),
    "HDFCBANK":   (1333,  "INE040A01034", 163500),
    "M&M":        (2031,  "INE101A01026", 288000),
    "HDFCLIFE":   (467,   "INE795G01014", 72000),
    "HDFCAMC":    (4244,  "INE127D01025", 410000),
    "SBIN":       (3045,  "INE062A01020", 81000),
    "ICICIBANK":  (4963,  "INE090A01021", 128000),
    "ITC":        (1660,  "INE154A01025", 43000),
    "LT":         (11483, "INE018A01030", 362000),
    "AXISBANK":   (5900,  "INE238A01034", 115000),
    "KOTAKBANK":  (1922,  "INE237A01028", 178000),
    "BHARTIARTL": (10604, "INE397D01024", 162000),
    "HINDUNILVR": (1394,  "INE030A01027", 245000),
    "WIPRO":      (3787,  "INE075A01022", 26000),
}

# symbol: (index token, spot paise, strike step paise, strikes each side, lot size, freeze qty)
INDICES = {
    "NIFTY":     (26000, 2452000, 5000, 40, 75, 1800),
    "BANKNIFTY": (26009, 5215000, 10000, 40, 35, 900),
}


def _expiry_ts(day: date) -> int:
    return int(datetime.combine(day, time(15, 30), tzinfo=IST).timestamp())


def _upcoming_weekdays(start: date, weekday: int, count: int) -> list[date]:
    d = start + timedelta(days=(weekday - start.weekday()) % 7)
    return [d + timedelta(weeks=i) for i in range(count)]


def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    d = nxt - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _monthly_expiries(start: date, weekday: int, count: int) -> list[date]:
    out, y, m = [], start.year, start.month
    while len(out) < count:
        d = _last_weekday_of_month(y, m, weekday)
        if d >= start:
            out.append(d)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def build_csv(today: date) -> str:
    rows: list[str] = []
    for symbol, (token, isin, price) in EQUITIES.items():
        lower, upper = price * 9 // 10, price * 11 // 10  # +/-10% band; midpoint = reference price
        rows.append(f"{token},NSECM,{token},NSECM,0,1,100000,{lower},{upper},0,,0,{symbol},STK,{isin},5")

    TUESDAY = 1
    next_token = 40000
    for symbol, (idx_token, spot, step, width, lot, freeze) in INDICES.items():
        rows.append(f"{idx_token},NSEIDX,{idx_token},NSEIDX,0,1,0,0,0,0,,0,{symbol},IDX,,5")

        monthly = _monthly_expiries(today, TUESDAY, 3)
        for exp in monthly:
            rows.append(f"{next_token},NSEFO,{idx_token},NSEIDX,{lot},{lot},{freeze},"
                        f"{spot * 9 // 10},{spot * 11 // 10},{_expiry_ts(exp)},,0,{symbol},FUTIDX,,5")
            next_token += 1

        # NIFTY has weekly options; BANKNIFTY monthly only.
        option_expiries = _upcoming_weekdays(today, TUESDAY, 4) if symbol == "NIFTY" else monthly
        atm = spot // step * step
        for exp in sorted(set(option_expiries)):
            ts = _expiry_ts(exp)
            for k in range(-width, width + 1):
                strike = atm + k * step
                for opt in ("CALL", "PUT"):
                    rows.append(f"{next_token},NSEFO,{idx_token},NSEIDX,{lot},{lot},{freeze},"
                                f"5,{spot},{ts},{opt},{strike},{symbol},OPTIDX,,5")
                    next_token += 1
    return HEADER + "\n" + "\n".join(rows) + "\n"


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "data/instruments.csv.gz")
    today = datetime.now(IST).date()
    text = build_csv(today)
    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out, "wb") as fh:
        fh.write(text.encode("utf-8"))
    out.with_suffix(out.suffix + ".date").write_text(today.isoformat(), encoding="utf-8")
    print(f"Wrote {text.count(chr(10)) - 1} instruments to {out} (for {today})")


if __name__ == "__main__":
    main()
