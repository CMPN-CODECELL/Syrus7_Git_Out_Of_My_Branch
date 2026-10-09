"""Kraken runtime against the fake 021: instrument refresh + disk cache, watchlist pinning."""
from app.config.settings import get_settings
from app.runtime import KrakenRuntime
from tests.fakes.fake_021 import BASE_URL, Fake021
from tests.fakes.market import instruments_csv


class NoLLM:
    def new_conversation(self, *a, **k):
        raise AssertionError("not used")


def runtime_for(fake: Fake021, tmp_path) -> KrakenRuntime:
    settings = get_settings().model_copy(update={
        "TradeApiBaseUrl": BASE_URL,
        "TradeApiUsername": fake.ucc,
        "TradeApiPassword": fake.password,
        "InstrumentsCachePath": str(tmp_path / "instruments.csv.gz"),
        "TradeApiRatePerSecond": 1000.0,
    })
    return KrakenRuntime(settings, llm=NoLLM(), transport=fake.transport())


async def test_refresh_instruments_loads_and_caches_to_disk(tmp_path):
    fake = Fake021()
    fake.instruments_csv = instruments_csv()
    runtime = runtime_for(fake, tmp_path)
    await runtime.refresh_instruments()
    assert len(runtime.instruments) > 30 and runtime.instruments.is_fresh()

    # A restart the same day loads from disk without calling 021.
    again = runtime_for(Fake021(), tmp_path)
    again._load_instruments_from_disk()
    assert len(again.instruments) == len(runtime.instruments)
    assert again.instruments.loaded_for == runtime.instruments.loaded_for
    await runtime.broker.aclose()
    await again.broker.aclose()


async def test_watchlist_pins_holdings_and_open_positions(tmp_path):
    fake = Fake021()
    fake.instruments_csv = instruments_csv()
    fake.positions = [
        {"exchange": "NSECM", "token": 2885, "product": "INTRADAY", "netQuantity": 10, "netPrice": 1},
        {"exchange": "NSECM", "token": 1333, "product": "INTRADAY", "netQuantity": 0, "netPrice": 0},  # closed: not pinned
    ]
    fake.holdings = [{"isin": "INE009A01021", "symbol": "INFY", "freeQty": 1, "btstQty": 0, "price": 1, "prevClose": 1}]
    runtime = runtime_for(fake, tmp_path)
    await runtime.refresh_instruments()
    await runtime.sync_watchlist()
    subs = runtime.socket._subs
    assert set(subs) == {(1, 2885), (1, 1594)}
    assert all(s.pinned and s.mode == "ltpc" for s in subs.values())
    assert runtime._watchlist == {"RELIANCE": "RELIANCE.NS", "INFY": "INFY.NS"}
    status = runtime.status()
    assert status["broker_configured"] and status["instruments_fresh"] and status["watchlist_symbols"] == 2
    assert status["instruments_for"]
    await runtime.broker.aclose()
