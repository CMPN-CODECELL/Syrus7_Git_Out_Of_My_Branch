"""Test doubles and builders for 021 market data: instruments CSV rows, binary frames, a fake socket."""
import struct
from datetime import date, datetime, time, timedelta, timezone

from domains.marketdata.domain.packets import FullPacket, LtpPacket, OptionChainPacket
from domains.marketdata.domain.price_cache import PriceCache

IST = timezone(timedelta(hours=5, minutes=30))
HEADER = ("token,exchange,underlying_token,underlying_exchange,min_lot_size,board_lot_quantity,freeze_quantity,"
          "lower_circuit,upper_circuit,expiry,option_type,strike_price,symbol,instrument_type,isin,ticksize")


def unix_expiry(day: date) -> int:
    return int(datetime.combine(day, time(15, 30), tzinfo=IST).timestamp())


def instruments_csv(expiry_day: date | None = None) -> str:
    expiry_day = expiry_day or (date.today() + timedelta(days=3))
    exp = unix_expiry(expiry_day)
    rows = [
        "2885,NSECM,2885,NSECM,0,1,100000,250000,300000,0,,0,RELIANCE,STK,INE002A01018,10",
        "2886,BSEEQ,2886,BSEEQ,0,1,100000,250000,300000,0,,0,RELIANCE,STK,INE002A01018,5",
        "1594,NSECM,1594,NSECM,0,1,100000,130000,170000,0,,0,INFY,STK,INE009A01021,10",
        "11536,NSECM,11536,NSECM,0,1,100000,300000,450000,0,,0,TCS,STK,INE467B01029,10",
        "1333,NSECM,1333,NSECM,0,1,100000,140000,190000,0,,0,HDFCBANK,STK,INE040A01034,10",
        "467,NSECM,467,NSECM,0,1,100000,50000,90000,0,,0,HDFCLIFE,STK,INE795G01014,5",
        "4244,NSECM,4244,NSECM,0,1,100000,300000,500000,0,,0,HDFCAMC,STK,INE127D01025,10",
        "2031,NSECM,2031,NSECM,0,1,100000,200000,400000,0,,0,M&M,STK,INE101A01026,10",
        "26000,NSEIDX,26000,NSEIDX,0,1,0,0,0,0,,0,NIFTY,IDX,,5",
        "26009,NSEIDX,26009,NSEIDX,0,1,0,0,0,0,,0,BANKNIFTY,IDX,,5",
    ]
    token = 40000
    for strike in range(2400000, 2560000, 10000):  # 24,000 .. 25,500 step 100
        for opt in ("CALL", "PUT"):
            token += 1
            rows.append(f"{token},NSEFO,26000,NSEIDX,75,75,1800,5,100000,{exp},{opt},{strike},NIFTY,OPTIDX,,5")
    # A far expiry to prove "nearest" picks the closest one
    far = unix_expiry(expiry_day + timedelta(days=28))
    rows.append(f"49999,NSEFO,26000,NSEIDX,75,75,1800,5,100000,{far},CALL,2450000,NIFTY,OPTIDX,,5")
    return HEADER + "\n" + "\n".join(rows) + "\n"


# ── binary frame builders (big-endian, per the 021 guide) ──
def ltp_packet(code: int, token: int, ltp: int, extra: tuple[str, int] | None = None) -> bytes:
    pkt = struct.pack(">HHIi", 1, code, token, ltp)
    if extra:
        pkt += bytes([0x6F if extra[0] == "o" else 0x63]) + struct.pack(">i", extra[1])
    return pkt


def full_nsecm(token: int, ltp: int, close: int, open_: int, high: int, low: int, bid: int, ask: int) -> bytes:
    buf = bytearray(220)
    struct.pack_into(">HHIi", buf, 0, 3, 1, token, ltp)
    struct.pack_into(">q", buf, 20, 123456)
    struct.pack_into(">iiii", buf, 44, close, open_, high, low)
    struct.pack_into(">qih", buf, 64, 10, bid, 3)            # best bid level
    struct.pack_into(">qih", buf, 64 + 5 * 14, 20, ask, 4)   # best ask level
    struct.pack_into(">I", buf, 216, 1_400_000_000)
    return bytes(buf)


def full_nsefo(token: int, ltp: int, oi: int) -> bytes:
    buf = bytearray(234)
    struct.pack_into(">HHH", buf, 0, 3, 2, 99)
    struct.pack_into(">Ii", buf, 6, token, ltp)
    struct.pack_into(">iiii", buf, 46, 100, 101, 102, 99)
    struct.pack_into(">q", buf, 206, oi)
    return bytes(buf)


def full_nseidx(token: int, value: int) -> bytes:
    buf = bytearray(36)
    struct.pack_into(">HHIi", buf, 0, 3, 3, token, value)
    struct.pack_into(">iiii", buf, 12, value - 100, value - 50, value + 50, value - 150)
    return bytes(buf)


def full_bse(code: int, token: int, ltp: int) -> bytes:
    buf = bytearray(262)
    struct.pack_into(">HHIi", buf, 0, 3, code, token, ltp)
    struct.pack_into(">iiii", buf, 48, 1, 2, 3, 4)
    struct.pack_into(">qii", buf, 68, 5, 777, 1)
    struct.pack_into(">qii", buf, 68 + 5 * 16, 6, 779, 1)
    return bytes(buf)


def oc_packet(code: int, token: int, ltp: int, oi: int, iv_x10000: int, delta_x10000: int) -> bytes:
    body = struct.pack(">HIHB", 9, token, code, 4)  # TC, token, exchange code, 4 entries
    body += bytes([1]) + struct.pack(">i", ltp)
    body += bytes([2]) + struct.pack(">q", oi)
    body += bytes([8]) + struct.pack(">iiiii", delta_x10000, 12, 3400, -2100, 500)
    body += bytes([4]) + struct.pack(">i", iv_x10000)
    return body


def heartbeat() -> bytes:
    return b"\x00\x0a"


def nse_order_frame(status: int, ucc: str, symbol: str, order_id: int, qty: int, price: int, reason: str = "") -> bytes:
    return (struct.pack(">HH", 4, status) + ucc.ljust(10).encode() + symbol.encode().ljust(20, b"\x00")
            + struct.pack(">Iii", order_id, qty, price) + reason.encode())


def bse_order_frame(status: int, ucc: str, code: int, token: int, order_id: int, qty: int, price: int, reason: str = "") -> bytes:
    return (struct.pack(">HH", 8, status) + ucc.ljust(10).encode()
            + struct.pack(">HIIii", code, token, order_id, qty, price) + reason.encode())


class FakeSocket:
    """Stands in for MarketSocketClient in tool tests: prices come from a pre-seeded PriceCache."""

    def __init__(self, cache: PriceCache):
        self.cache = cache
        self.ensured: list[tuple[list, str]] = []

    @property
    def connected(self) -> bool:
        return self.cache.connected

    async def ensure(self, keys, mode="ltp", *, pinned=False):
        keys = list(keys)
        self.ensured.append((keys, mode))
        return keys

    async def wait_fresh(self, keys, timeout):
        return {k for k in keys if self.cache.get(*k) is not None}


def seeded_cache(prices: dict[tuple[int, int], int], *, prev_close: dict | None = None, oc: dict | None = None) -> PriceCache:
    cache = PriceCache()
    cache.on_connected()
    for (code, token), ltp in prices.items():
        cache.apply(LtpPacket(code, token, ltp, prev_close=(prev_close or {}).get((code, token))))
    for (code, token), (ltp, oi, iv, delta) in (oc or {}).items():
        cache.apply(OptionChainPacket(code, token, ltp=ltp, oi=oi, iv=iv, greeks={"delta": delta}))
    return cache


__all__ = ["FullPacket", "seeded_cache", "FakeSocket", "instruments_csv"]
