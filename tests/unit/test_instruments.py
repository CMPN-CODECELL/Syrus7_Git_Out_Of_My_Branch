from datetime import date, datetime, timedelta, timezone

from domains.broker.infrastructure.instruments import (
    IST,
    InstrumentRepository,
    InstrumentStore,
    expiry_to_date,
    parse_instruments_csv,
)
from tests.fakes.market import HEADER, instruments_csv, unix_expiry


def store(expiry_day=None) -> InstrumentStore:
    return InstrumentStore(parse_instruments_csv(instruments_csv(expiry_day)), loaded_for=date.today())


def test_parses_guide_sample_row():
    text = HEADER + "\n22699,NSECM,22699,NSECM,0,100,984600,9649,10663,0,,0,747HR36,STK,IN1620230376,1\n"
    (inst,) = parse_instruments_csv(text)
    assert inst.token == 22699 and inst.board_lot_quantity == 100 and inst.ticksize == 1
    assert inst.lower_circuit == 9649 and inst.request_exchange == "NSE" and inst.ws_code == 1


def test_unknown_columns_and_bad_rows_do_not_break_parsing():
    text = HEADER + ",new_col\n2885,NSECM,2885,NSECM,0,1,1,1,1,0,,0,RELIANCE,STK,X,10,zzz\nnot,a,row\n"
    rows = parse_instruments_csv(text)
    assert [r.symbol for r in rows] == ["RELIANCE"]


def test_equity_prefers_nse_over_bse():
    s = store()
    assert s.equity("reliance").exchange == "NSECM"
    assert s.equity_by_isin("INE002A01018").exchange == "NSECM"


def test_index_is_data_only():
    nifty = store().index("NIFTY")
    assert nifty.is_index and nifty.request_exchange is None


def test_ambiguous_prefix_search_lists_candidates():
    names = {i.symbol for i in store().search("HDFC")}
    assert {"HDFCBANK", "HDFCLIFE", "HDFCAMC"} <= names


def test_nearest_expiry_on_or_after_today():
    expiry_day = date.today() + timedelta(days=3)
    s = store(expiry_day)
    raw = s.nearest_expiry("NIFTY", today=date.today())
    assert expiry_to_date(raw) == expiry_day


def test_expired_contracts_are_skipped():
    s = store(date.today() - timedelta(days=1))
    raw = s.nearest_expiry("NIFTY", today=date.today())
    assert expiry_to_date(raw) == date.today() + timedelta(days=27)  # falls through to the far expiry


def test_expiry_encodings():
    today = date(2026, 10, 9)
    target = date(2026, 10, 13)
    unix = unix_expiry(target)
    assert expiry_to_date(unix, today=today) == target
    assert expiry_to_date(unix * 1000, today=today) == target
    assert expiry_to_date(20261013, today=today) == target
    since_1980 = int((datetime(2026, 10, 13, 15, 30, tzinfo=IST) - datetime(1980, 1, 1, tzinfo=IST)).total_seconds())
    assert expiry_to_date(since_1980, today=today) == target
    assert expiry_to_date(0, today=today) is None


def test_freshness_is_by_ist_trading_date():
    s = store()
    s.loaded_for = date(2026, 10, 8)
    assert not s.is_fresh(datetime(2026, 10, 9, 3, 0, tzinfo=timezone.utc))
    s.loaded_for = date(2026, 10, 9)
    assert s.is_fresh(datetime(2026, 10, 9, 3, 0, tzinfo=timezone.utc))


def test_disk_cache_round_trip(tmp_path):
    repo = InstrumentRepository(str(tmp_path / "inst.csv.gz"))
    assert repo.load() == (None, None)
    repo.save(b"token\n1\n", date(2026, 10, 9))
    assert repo.load() == ("token\n1\n", date(2026, 10, 9))
