"""Binary frame parsing against the layouts in the 021 API guide."""
from domains.marketdata.domain.packets import (
    ORDER_STATUS_EVENTS,
    FullPacket,
    LtpPacket,
    OptionChainPacket,
    parse_market_frame,
    parse_order_frame,
)
from tests.fakes.market import (
    bse_order_frame,
    full_bse,
    full_nsecm,
    full_nsefo,
    full_nseidx,
    heartbeat,
    ltp_packet,
    nse_order_frame,
    oc_packet,
)


def test_ltp_packet():
    (pkt,) = parse_market_frame(ltp_packet(1, 2885, 140550)).packets
    assert pkt == LtpPacket(1, 2885, 140550)


def test_several_packets_per_frame_with_heartbeat():
    frame = ltp_packet(1, 2885, 140000) + heartbeat() + ltp_packet(2, 43210, 1500)
    result = parse_market_frame(frame)
    assert [(p.exchange_code, p.token, p.ltp) for p in result.packets] == [(1, 2885, 140000), (2, 43210, 1500)]
    assert result.heartbeats == 1 and result.error is None


def test_snapshot_extra_bytes_for_ltpo_and_ltpc():
    frame = ltp_packet(1, 2885, 140000, ("o", 139000)) + ltp_packet(1, 1594, 150000, ("c", 151000)) + ltp_packet(1, 1, 5)
    a, b, c = parse_market_frame(frame).packets
    assert a.open == 139000 and a.prev_close is None
    assert b.prev_close == 151000 and b.open is None
    assert c.ltp == 5


def test_full_packets_per_exchange_layout():
    frame = full_nsecm(2885, 140000, 139200, 139500, 141000, 138800, 139990, 140010) + full_nsefo(43210, 1500, 987654) + full_nseidx(26000, 2450000) + full_bse(4, 500325, 140100)
    eq, fo, idx, bse = parse_market_frame(frame).packets
    assert isinstance(eq, FullPacket) and eq.token == 2885 and eq.ltp == 140000
    assert (eq.close, eq.open, eq.high, eq.low) == (139200, 139500, 141000, 138800)
    assert eq.best_bid == 139990 and eq.best_ask == 140010 and eq.volume == 123456
    assert fo.token == 43210 and fo.ltp == 1500 and fo.oi == 987654  # packet id at offset 4 skipped
    assert idx.token == 26000 and idx.ltp == 2450000 and idx.close == 2449900
    assert bse.token == 500325 and bse.best_bid == 777 and bse.best_ask == 779


def test_option_chain_packet_with_scaled_values():
    (pkt,) = parse_market_frame(oc_packet(2, 40011, 12345, 5_000_000, 2534, 5123)).packets
    assert isinstance(pkt, OptionChainPacket)
    assert pkt.token == 40011 and pkt.exchange_code == 2 and pkt.ltp == 12345 and pkt.oi == 5_000_000
    assert pkt.iv == 25.34  # 2534 = 25.34%
    assert pkt.greeks["delta"] == 0.5123 and pkt.greeks["theta"] == -0.21


def test_unknown_tc_stops_without_guessing():
    frame = ltp_packet(1, 1, 100) + b"\x00\x63" + b"\x00" * 10
    result = parse_market_frame(frame)
    assert len(result.packets) == 1 and result.error == "unknown TC 99" and result.unparsed_bytes == 12


def test_truncated_full_packet_reported():
    result = parse_market_frame(full_nsecm(1, 1, 1, 1, 1, 1, 1, 1)[:100])
    assert result.packets == [] and "bad full packet" in result.error


def test_nse_order_event_with_reason():
    pkt = parse_order_frame(nse_order_frame(3, "HACK344", "RELIANCE", 1042, -5, 140000, "Insufficient funds"))
    assert ORDER_STATUS_EVENTS[pkt.status_code] == "REJECTED"
    assert (pkt.ucc, pkt.symbol, pkt.order_id, pkt.qty, pkt.price) == ("HACK344", "RELIANCE", "1042", -5, 140000)
    assert pkt.reason == "Insufficient funds"


def test_bse_order_event():
    pkt = parse_order_frame(bse_order_frame(1, "HACK344", 4, 500325, 77, 10, 140100))
    assert ORDER_STATUS_EVENTS[pkt.status_code] == "TRADE"
    assert (pkt.exchange_code, pkt.token, pkt.order_id, pkt.qty, pkt.price, pkt.reason) == (4, 500325, "77", 10, 140100, None)
