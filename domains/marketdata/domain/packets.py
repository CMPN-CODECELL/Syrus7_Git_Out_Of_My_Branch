"""
Parsers for 021's binary websocket frames (big-endian, prices in paise).

Market socket — one frame holds many packets back to back; each starts with a 2-byte TC:
  TC 1  LTP (ltp/ltpo/ltpc)        12 bytes (+5 in snapshot frames for ltpo/ltpc: 'o'|'c' + int32)
  TC 3  Full                       length by exchange code: 1→220, 2→234, 3→36, 4/5/6→262
  TC 9  Option chain (oc)          9 bytes header + variable filter entries
  TC 10 Heartbeat                  2 bytes
Orders socket — one packet per frame:
  TC 4  NSE order event            46 bytes + optional ASCII reason
  TC 8  BSE order event            32 bytes + optional ASCII reason
An unknown TC makes the rest of the frame unparseable (lengths are TC-specific), so parsing
stops there and the remainder is reported, never guessed.
"""
import struct
from dataclasses import dataclass, field
from typing import Optional, Union

TC_LTP = 1
TC_FULL = 3
TC_ORDER_NSE = 4
TC_ORDER_BSE = 8
TC_OPTION_CHAIN = 9
TC_HEARTBEAT = 10

FULL_LENGTH = {1: 220, 2: 234, 3: 36, 4: 262, 5: 262, 6: 262}
_SNAPSHOT_EXTRA = {0x6F: "open", 0x63: "prev_close"}  # 'o', 'c'

# Seconds since 1980-01-01 00:00 IST -> Unix seconds.
EXCHANGE_EPOCH_OFFSET = 315513000

# oc filter id -> (name, byte length)
_OC_FIELDS = {1: ("ltp", 4), 2: ("oi", 8), 3: ("volume", 8), 4: ("iv", 4), 7: ("md", 32), 8: ("greeks", 20), 9: ("pcr_oi", 4)}


@dataclass
class LtpPacket:
    exchange_code: int
    token: int
    ltp: int
    open: Optional[int] = None
    prev_close: Optional[int] = None


@dataclass
class FullPacket:
    exchange_code: int
    token: int
    ltp: int
    open: int
    high: int
    low: int
    close: int
    volume: Optional[int] = None
    oi: Optional[int] = None
    best_bid: Optional[int] = None
    best_ask: Optional[int] = None
    exchange_time: Optional[int] = None


@dataclass
class OptionChainPacket:
    exchange_code: int
    token: int
    ltp: Optional[int] = None
    oi: Optional[int] = None
    volume: Optional[int] = None
    iv: Optional[float] = None  # percent, e.g. 25.34
    best_bid: Optional[int] = None
    best_ask: Optional[int] = None
    bid_qty: Optional[int] = None
    ask_qty: Optional[int] = None
    greeks: Optional[dict] = None
    pcr_oi: Optional[float] = None


@dataclass
class OrderUpdatePacket:
    tc: int
    status_code: int
    ucc: str
    order_id: str
    qty: int
    price: int
    exchange_code: Optional[int] = None
    token: Optional[int] = None
    symbol: Optional[str] = None
    reason: Optional[str] = None


@dataclass
class ParseResult:
    packets: list = field(default_factory=list)
    heartbeats: int = 0
    unparsed_bytes: int = 0
    error: Optional[str] = None


MarketPacket = Union[LtpPacket, FullPacket, OptionChainPacket]

_I16 = struct.Struct(">h")
_U16 = struct.Struct(">H")
_I32 = struct.Struct(">i")
_U32 = struct.Struct(">I")
_I64 = struct.Struct(">q")


def _u16(buf: bytes, off: int) -> int:
    return _U16.unpack_from(buf, off)[0]


def _i32(buf: bytes, off: int) -> int:
    return _I32.unpack_from(buf, off)[0]


def _u32(buf: bytes, off: int) -> int:
    return _U32.unpack_from(buf, off)[0]


def _i64(buf: bytes, off: int) -> int:
    return _I64.unpack_from(buf, off)[0]


def _parse_full(buf: bytes, off: int, code: int) -> FullPacket:
    if code == 1:  # NSECM
        level, depth = 14, off + 64
        pkt = FullPacket(code, _u32(buf, off + 4), _i32(buf, off + 8),
                         open=_i32(buf, off + 48), high=_i32(buf, off + 52), low=_i32(buf, off + 56),
                         close=_i32(buf, off + 44), volume=_i64(buf, off + 20),
                         exchange_time=_u32(buf, off + 216))
    elif code == 2:  # NSEFO has a 2-byte packet id at offset 4
        level, depth = 14, off + 66
        pkt = FullPacket(code, _u32(buf, off + 6), _i32(buf, off + 10),
                         close=_i32(buf, off + 46), open=_i32(buf, off + 50), high=_i32(buf, off + 54),
                         low=_i32(buf, off + 58), volume=_i64(buf, off + 22), oi=_i64(buf, off + 206),
                         exchange_time=_u32(buf, off + 230))
    elif code == 3:  # NSEIDX
        return FullPacket(code, _u32(buf, off + 4), _i32(buf, off + 8),
                          close=_i32(buf, off + 12), open=_i32(buf, off + 16), high=_i32(buf, off + 20),
                          low=_i32(buf, off + 24), exchange_time=_u32(buf, off + 28))
    else:  # BSE 4/5/6
        level, depth = 16, off + 68
        pkt = FullPacket(code, _u32(buf, off + 4), _i32(buf, off + 8),
                         close=_i32(buf, off + 48), open=_i32(buf, off + 52), high=_i32(buf, off + 56),
                         low=_i32(buf, off + 60), volume=_i64(buf, off + 24), oi=_i64(buf, off + 228),
                         exchange_time=_u32(buf, off + 244))
    # Depth: 5 bids (best first) then 5 asks; level = qty(8) + price(4) + orders(2|4).
    bid_price = _i32(buf, depth + 8)
    ask_price = _i32(buf, depth + 5 * level + 8)
    pkt.best_bid = bid_price or None
    pkt.best_ask = ask_price or None
    return pkt


def _parse_option_chain(buf: bytes, off: int) -> tuple[Optional[OptionChainPacket], int, Optional[str]]:
    """Returns (packet, bytes consumed, error). TC9 layout: TC(2) token(4) exch(2) count(1) entries."""
    if len(buf) - off < 9:
        return None, 0, "truncated option-chain header"
    token = _u32(buf, off + 2)
    code = _u16(buf, off + 6)
    count = buf[off + 8]
    pkt = OptionChainPacket(exchange_code=code, token=token)
    pos = off + 9
    for _ in range(count):
        if pos >= len(buf):
            return None, 0, "truncated option-chain entry"
        field_id = buf[pos]
        spec = _OC_FIELDS.get(field_id)
        if spec is None:
            return None, 0, f"unknown option-chain field id {field_id}"
        name, size = spec
        if pos + 1 + size > len(buf):
            return None, 0, "truncated option-chain value"
        v = pos + 1
        if name == "ltp":
            pkt.ltp = _i32(buf, v)
        elif name == "oi":
            pkt.oi = _i64(buf, v)
        elif name == "volume":
            pkt.volume = _i64(buf, v)
        elif name == "iv":
            pkt.iv = round(_i32(buf, v) / 100.0, 2)  # x10,000 fraction -> percent
        elif name == "md":
            pkt.best_bid, pkt.best_ask, pkt.bid_qty, pkt.ask_qty = (
                _i64(buf, v), _i64(buf, v + 8), _i64(buf, v + 16), _i64(buf, v + 24),
            )
        elif name == "greeks":
            keys = ("delta", "gamma", "vega", "theta", "rho")
            pkt.greeks = {k: round(_i32(buf, v + 4 * i) / 10_000.0, 4) for i, k in enumerate(keys)}
        elif name == "pcr_oi":
            pkt.pcr_oi = round(_i32(buf, v) / 100.0, 2)
        pos = v + size
    return pkt, pos - off, None


def parse_market_frame(frame: bytes) -> ParseResult:
    result = ParseResult()
    off = 0
    n = len(frame)
    while off < n:
        if n - off < 2:
            result.unparsed_bytes = n - off
            result.error = "trailing byte"
            break
        tc = _u16(frame, off)
        if tc == TC_HEARTBEAT:
            result.heartbeats += 1
            off += 2
            continue
        if tc == TC_LTP:
            if n - off < 12:
                result.unparsed_bytes, result.error = n - off, "truncated LTP packet"
                break
            pkt = LtpPacket(_u16(frame, off + 2), _u32(frame, off + 4), _i32(frame, off + 8))
            off += 12
            # Snapshot frames: ltpo/ltpc carry 'o'|'c' + int32. A new packet always starts with 0x00.
            if off < n and frame[off] in _SNAPSHOT_EXTRA and n - off >= 5:
                setattr(pkt, _SNAPSHOT_EXTRA[frame[off]], _i32(frame, off + 1))
                off += 5
            result.packets.append(pkt)
            continue
        if tc == TC_FULL:
            if n - off < 4:
                result.unparsed_bytes, result.error = n - off, "truncated full packet"
                break
            code = _u16(frame, off + 2)
            length = FULL_LENGTH.get(code)
            if length is None or n - off < length:
                result.unparsed_bytes, result.error = n - off, f"bad full packet (exchange {code})"
                break
            result.packets.append(_parse_full(frame, off, code))
            off += length
            continue
        if tc == TC_OPTION_CHAIN:
            pkt, used, error = _parse_option_chain(frame, off)
            if error:
                result.unparsed_bytes, result.error = n - off, error
                break
            result.packets.append(pkt)
            off += used
            continue
        result.unparsed_bytes, result.error = n - off, f"unknown TC {tc}"
        break
    return result


def _ascii(buf: bytes) -> str:
    return buf.split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()


def _reason(buf: bytes) -> Optional[str]:
    text = "".join(ch for ch in buf.decode("ascii", errors="replace") if ch.isprintable()).strip()
    return text[:300] or None


def parse_order_frame(frame: bytes) -> Optional[OrderUpdatePacket]:
    if len(frame) < 2:
        return None
    tc = _u16(frame, 0)
    if tc == TC_ORDER_NSE and len(frame) >= 46:
        return OrderUpdatePacket(
            tc=tc, status_code=_u16(frame, 2), ucc=_ascii(frame[4:14]),
            symbol=_ascii(frame[14:34]) or None, order_id=str(_u32(frame, 34)),
            qty=_i32(frame, 38), price=_i32(frame, 42), reason=_reason(frame[46:]),
        )
    if tc == TC_ORDER_BSE and len(frame) >= 32:
        return OrderUpdatePacket(
            tc=tc, status_code=_u16(frame, 2), ucc=_ascii(frame[4:14]),
            exchange_code=_u16(frame, 14), token=_u32(frame, 16), order_id=str(_u32(frame, 20)),
            qty=_i32(frame, 24), price=_i32(frame, 28), reason=_reason(frame[32:]),
        )
    return None


ORDER_STATUS_EVENTS = {
    1: "TRADE", 2: "ACCEPTED", 3: "REJECTED", 4: "SL_TRIGGERED", 5: "MODIFY_ACCEPTED",
    6: "MODIFY_REJECTED", 7: "CANCELLED", 8: "CANCEL_REJECTED", 9: "PRICE_CONFIRMATION",
}
