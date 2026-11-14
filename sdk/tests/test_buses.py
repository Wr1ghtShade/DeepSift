from __future__ import annotations

import asyncio
import json

import fakeredis
import pytest
from deepsift_sdk import EventKind
from deepsift_sdk.bus import MemoryBus, RedisBus
from deepsift_sdk.worker import serve
from fakes import FakeService


@pytest.fixture
async def redis_bus():
    bus = RedisBus(fakeredis.FakeAsyncRedis(decode_responses=True))
    yield bus
    await bus.close()


async def run_worker_until(bus, predicate, limit=5.0, block_ms=50):
    stop = asyncio.Event()
    worker = asyncio.create_task(
        serve(FakeService(), bus, instance_id="test-1", stop=stop, block_ms=block_ms)
    )
    try:
        await asyncio.wait_for(predicate(), limit)
    finally:
        stop.set()
        await asyncio.wait_for(worker, limit)


async def test_worker_over_memory_bus(username_task):
    bus = MemoryBus()
    await bus.publish_task(username_task)
    received = []

    async def until_completed():
        while True:
            event = await bus.events.get()
            received.append(event)
            if event.is_final:
                return

    await run_worker_until(bus, until_completed)
    assert received[-1].event is EventKind.COMPLETED
    assert bus.acked == ["1"]
    assert ("fake", "test-1") in bus.heartbeats
    assert "fake" not in bus.registry  # deregistered on stop


async def test_redis_bus_round_trip(redis_bus, username_task):
    await redis_bus.publish_task(username_task)
    deliveries = await redis_bus.read_tasks("fake", "c1", count=10, block_ms=10)
    assert [d.task.task_id for d in deliveries] == [username_task.task_id]
    # Not acknowledged yet: still pending for the group.
    pending = await redis_bus.redis.xpending("deepsift:tasks:fake", "fake")
    assert pending["pending"] == 1
    await redis_bus.ack("fake", deliveries[0])
    pending = await redis_bus.redis.xpending("deepsift:tasks:fake", "fake")
    assert pending["pending"] == 0


async def test_worker_over_redis_bus(redis_bus, username_task):
    await redis_bus.publish_task(username_task)
    received = []

    async def until_completed():
        last_id = "0"
        while True:
            for message_id, event in await redis_bus.read_events(last_id, block_ms=0):
                last_id = message_id
                received.append(event)
                if event.is_final:
                    return
            await asyncio.sleep(0.01)

    # fakeredis does not support blocking reads well: poll instead.
    await run_worker_until(redis_bus, until_completed, block_ms=0)
    kinds = [e.event for e in received]
    assert kinds[0] is EventKind.STARTED
    assert kinds[-1] is EventKind.COMPLETED
    assert EventKind.ENTITY in kinds

    registry = await redis_bus.redis.xrange("deepsift:registry")
    assert [fields["event"] for _, fields in registry] == ["register", "deregister"]
    assert json.loads(registry[0][1]["manifest"])["name"] == "fake"
    beat = json.loads(await redis_bus.redis.get("deepsift:heartbeat:fake:test-1"))
    assert beat["state"] in {"ready", "busy"}
    assert await redis_bus.redis.ttl("deepsift:heartbeat:fake:test-1") > 0


async def test_worker_waits_for_setup_then_takes_tasks(username_task, monkeypatch):
    from deepsift_sdk import worker

    monkeypatch.setattr(worker, "HEARTBEAT_EVERY", 0.05)

    class NotLoggedIn(FakeService):
        logged_in = False

        async def missing_setup(self) -> list[str]:
            return [] if self.logged_in else ["log in: fake-login"]

    service = NotLoggedIn()
    bus = MemoryBus()
    stop = asyncio.Event()
    job = asyncio.create_task(serve(service, bus, instance_id="w", stop=stop, block_ms=20))
    await asyncio.sleep(0.15)
    beat = bus.heartbeats[("fake", "w")]
    assert beat["state"] == "needs_config"
    assert beat["missing"] == ["log in: fake-login"]
    await bus.publish_task(username_task)
    await asyncio.sleep(0.1)
    assert bus.events.empty()  # not configured: the task waits

    service.logged_in = True  # the operator finishes the setup, no restart
    event = await asyncio.wait_for(bus.events.get(), 2)
    assert event.task_id == username_task.task_id
    assert bus.heartbeats[("fake", "w")]["missing"] == []
    stop.set()
    await asyncio.wait_for(job, 2)
