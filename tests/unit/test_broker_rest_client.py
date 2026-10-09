"""
021 gateway behaviour under the sandbox's deliberate failures (fault-injecting fake 021).
"""
import asyncio

import httpx
import pytest

from domains.broker.domain.errors import (
    BrokerAuthError,
    BrokerForbiddenError,
    BrokerNotConfiguredError,
    BrokerOutcomeUnknownError,
    BrokerRateLimitedError,
    BrokerRejectedError,
    BrokerSafeModeError,
    BrokerUnavailableError,
    BrokerWrongClusterError,
)
from domains.broker.infrastructure.rest_client import TradeRestClient
from shared.contracts.orders import OrderPayload
from tests.fakes.fake_021 import BASE_URL, Fake021

ORDER = OrderPayload(exchange="NSE", token=2885, qty=1, price=0, product="CNC")


class SleepRecorder:
    """Virtual time: sleeping advances the clock the rate limiter reads."""

    def __init__(self):
        self.calls: list[float] = []
        self.now = 0.0

    def clock(self) -> float:
        return self.now

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        self.now += seconds


def make_client(fake: Fake021, *, retries: int = 3, sleep=None, username=None, password=None) -> TradeRestClient:
    sleep = sleep or SleepRecorder()
    return TradeRestClient(
        BASE_URL,
        fake.ucc if username is None else username,
        fake.password if password is None else password,
        rate_per_second=1000,
        max_get_retries=retries,
        transport=fake.transport(),
        sleep=sleep,
        clock=sleep.clock,
        rng=lambda: 1.0,
    )


async def test_concurrent_reads_share_one_login():
    fake = Fake021()
    fake.positions = [{"token": 2885}]
    client = make_client(fake)
    results = await asyncio.gather(*(client.get_positions() for _ in range(5)))
    assert all(r == [{"token": 2885}] for r in results)
    assert fake.logins == 1


async def test_revoked_token_triggers_single_relogin_and_read_is_replayed():
    fake = Fake021()
    client = make_client(fake)
    await client.get_positions()
    fake.revoke_token()  # someone else logged in with the same UCC
    results = await asyncio.gather(*(client.get_holdings() for _ in range(4)))
    assert results == [[], [], [], []]
    assert fake.logins == 2  # exactly one re-login despite four concurrent 401s


@pytest.mark.parametrize("status", [500, 503, 429])
async def test_get_retries_transient_errors_then_succeeds(status):
    fake = Fake021()
    fake.holdings = [{"symbol": "INFY"}]
    sleep = SleepRecorder()
    client = make_client(fake, sleep=sleep)
    await client.get_holdings()
    fake.fail_next("/portfolio/holdings", status=status, count=2)
    assert await client.get_holdings() == [{"symbol": "INFY"}]
    assert fake.count("GET", "/portfolio/holdings") == 4  # 1 warm-up + 2 failures + 1 success
    assert len(sleep.calls) >= 2  # backed off before each retry (429 also pauses the shared limiter)


async def test_get_gives_up_after_max_retries_with_honest_error():
    fake = Fake021()
    client = make_client(fake, retries=3)
    fake.fail_next("/portfolio/positions", status=503, count=10)
    with pytest.raises(BrokerUnavailableError):
        await client.get_positions()
    assert fake.count("GET", "/portfolio/positions") == 4  # first try + 3 retries, never more


async def test_429_honours_retry_after():
    fake = Fake021()
    sleep = SleepRecorder()
    client = make_client(fake, sleep=sleep)
    fake.fail_next("/trades", status=429, headers={"Retry-After": "2.5"})
    assert await client.get_trades() == []
    assert max(sleep.calls) >= 2.5


async def test_429_after_retries_exhausted_is_rate_limited_error():
    fake = Fake021()
    client = make_client(fake, retries=1)
    fake.fail_next("/orders", method="GET", status=429, count=5)
    with pytest.raises(BrokerRateLimitedError):
        await client.get_orders()


async def test_html_gateway_error_on_get_is_retried():
    fake = Fake021()
    client = make_client(fake)
    fake.fail_next("/portfolio/positions", status=502, body=b"<html>Bad Gateway</html>")
    assert await client.get_positions() == []


async def test_read_timeout_on_get_is_retried():
    fake = Fake021()
    client = make_client(fake)
    await client.get_positions()
    fake.fail_next("/portfolio/positions", exc=httpx.ReadTimeout)
    assert await client.get_positions() == []
    assert fake.count("GET", "/portfolio/positions") == 3


# ── order actions: never retried, never blindly resent ──

async def test_order_post_timeout_after_accept_is_outcome_unknown_and_not_resent():
    fake = Fake021()
    client = make_client(fake)
    fake.fail_next("/orders", method="POST", exc=httpx.ReadTimeout, accept_first=True)
    with pytest.raises(BrokerOutcomeUnknownError):
        await client.place_order(ORDER)
    assert fake.count("POST", "/orders") == 1
    assert len(fake.orders) == 1  # 021 did book it: only reconciliation can tell, so no resend


async def test_order_post_503_is_outcome_unknown_not_retried():
    fake = Fake021()
    client = make_client(fake)
    fake.fail_next("/orders", method="POST", status=503)
    with pytest.raises(BrokerOutcomeUnknownError):
        await client.place_order(ORDER)
    assert fake.count("POST", "/orders") == 1


async def test_order_risk_rejection_500_is_shown_as_rejection():
    fake = Fake021()
    client = make_client(fake)
    fake.fail_next("/orders", method="POST", status=500, error="Insufficient funds")
    with pytest.raises(BrokerRejectedError) as info:
        await client.place_order(ORDER)
    assert "Insufficient funds" in info.value.user_message()
    assert fake.count("POST", "/orders") == 1


async def test_order_after_token_revocation_is_not_sent_and_session_renewed():
    fake = Fake021()
    client = make_client(fake)
    await client.get_positions()
    fake.revoke_token()
    with pytest.raises(BrokerAuthError) as info:
        await client.place_order(ORDER)
    assert "NOT sent" in str(info.value)
    assert fake.count("POST", "/orders") == 1 and not fake.orders
    assert fake.logins == 2
    assert await client.place_order(ORDER)  # the next explicit attempt works


async def test_connect_error_on_order_means_not_sent():
    fake = Fake021()
    client = make_client(fake)
    await client.get_positions()
    fake.fail_next("/orders", method="POST", exc=httpx.ConnectError)
    with pytest.raises(BrokerUnavailableError) as info:
        await client.place_order(ORDER)
    assert "not sent" in str(info.value)
    assert not fake.orders


async def test_successful_order_returns_order_id():
    fake = Fake021()
    client = make_client(fake)
    order_id = await client.place_order(ORDER)
    assert order_id == "1001"
    assert fake.orders[0]["token"] == 2885


@pytest.mark.parametrize("status,error_type", [(403, BrokerForbiddenError), (421, BrokerWrongClusterError), (422, BrokerSafeModeError)])
async def test_configuration_errors_are_typed_and_not_retried(status, error_type):
    fake = Fake021()
    client = make_client(fake)
    fake.fail_next("/portfolio/positions", status=status, error="blocked", count=5)
    with pytest.raises(error_type):
        await client.get_positions()
    assert fake.count("GET", "/portfolio/positions") == 1


async def test_wrong_credentials_raise_auth_error():
    fake = Fake021()
    client = make_client(fake, password="wrong")
    with pytest.raises(BrokerAuthError):
        await client.get_positions()


async def test_missing_credentials_raise_not_configured():
    fake = Fake021()
    client = make_client(fake, username="", password="")
    with pytest.raises(BrokerNotConfiguredError):
        await client.get_positions()
    assert fake.requests == []


async def test_instruments_download_is_decompressed():
    fake = Fake021()
    fake.instruments_csv = "token,exchange\n1,NSECM\n"
    client = make_client(fake)
    assert (await client.download_instruments()).decode() == "token,exchange\n1,NSECM\n"


async def test_password_never_in_repr():
    client = make_client(Fake021())
    assert "test-password" not in repr(client.tokens)


async def test_random_faults_reads_still_answer():
    fake = Fake021(seed=3)
    fake.positions = [{"token": 1}]
    fake.random_fault_rate = 0.3
    client = make_client(fake, retries=6)
    for _ in range(20):
        assert await client.get_positions() == [{"token": 1}]
