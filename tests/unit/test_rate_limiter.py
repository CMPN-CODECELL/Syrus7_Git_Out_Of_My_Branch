from domains.broker.infrastructure.rate_limiter import TokenBucket


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


async def test_bucket_paces_requests_beyond_burst():
    clock = FakeClock()
    bucket = TokenBucket(2.0, burst=2, clock=clock, sleep=clock.sleep)
    for _ in range(4):
        await bucket.acquire()
    assert clock.now >= 1.0 - 1e-9  # 2 burst + 2 more at 2/s


async def test_penalize_blocks_everyone_after_429():
    clock = FakeClock()
    bucket = TokenBucket(100.0, burst=10, clock=clock, sleep=clock.sleep)
    bucket.penalize(3.0)
    await bucket.acquire()
    assert clock.now >= 3.0
