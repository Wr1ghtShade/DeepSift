from __future__ import annotations

import pytest
from deepsift_sdk import ErrorCode, EventKind
from deepsift_sdk.local import LocalRun
from deepsift_sdk.ratelimit import FileLimiter
from deepsift_sdk.service import ServiceError
from fakes import FakeService, make_manifest


class Clock:
    def __init__(self, start: float) -> None:
        self.now = start
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(round(seconds, 3))
        self.now += seconds


def limiter(path, clock, interval=10, daily=50):
    return FileLimiter(path, interval, daily, clock=clock, sleep=clock.sleep)


async def test_spaces_calls_across_instances(tmp_path):
    clock = Clock(1_763_100_000.0)
    assert await limiter(tmp_path, clock).acquire() == 49
    clock.now += 3
    assert await limiter(tmp_path, clock).acquire() == 48  # another process, same file
    assert clock.slept == [7.0]


async def test_reserved_slots_queue_up(tmp_path):
    clock = Clock(1_763_100_000.0)
    first = limiter(tmp_path, clock)
    # Reserve twice without letting time pass: the second slot is one interval later.
    slot1, _ = first._reserve()
    slot2, _ = first._reserve()
    assert slot2 - slot1 == 10


async def test_daily_cap_and_reset(tmp_path):
    clock = Clock(1_763_100_000.0)
    lim = limiter(tmp_path, clock, interval=0, daily=2)
    await lim.acquire()
    await lim.acquire()
    with pytest.raises(ServiceError) as caught:
        await lim.acquire()
    assert caught.value.info.code is ErrorCode.RATE_LIMITED
    assert caught.value.info.retryable is False
    clock.now += 86_400
    assert await lim.acquire() == 1


async def test_services_missing_required_secrets_are_skipped(monkeypatch):
    class Keyed(FakeService):
        _manifest = make_manifest("keyed", secrets=["DEEPSIFT_TEST_KEY"])

    monkeypatch.delenv("DEEPSIFT_TEST_KEY", raising=False)
    services = {"fake": FakeService(), "keyed": Keyed()}
    events = [e async for e in LocalRun(services).run("alice")]
    assert {e.service for e in events} == {"fake"}
    events = [e async for e in LocalRun(services).run("alice", only=["keyed"])]
    assert [e.error.code for e in events if e.event is EventKind.FAILED] == [ErrorCode.NEEDS_CONFIG]
