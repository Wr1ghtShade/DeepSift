"""The gateway over Redis Streams, with real workers (fakeredis, same event loop)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import fakeredis
import pytest
from deepsift_gateway.db import (
    Investigation,
    Run,
    RunStatus,
    TaskRow,
    create_schema,
    make_engine,
    make_sessionmaker,
    now,
)
from deepsift_gateway.executors import BusExecutor
from deepsift_gateway.hub import Hub
from deepsift_gateway.orchestrator import Orchestrator
from deepsift_sdk.bus.redis import RedisBus
from deepsift_sdk.entities import EntityType
from deepsift_sdk.worker import serve
from fakes import AvatarProfileService, FakeHashService, FakeService
from sqlalchemy import select


@pytest.fixture
async def stack(tmp_path: Path) -> AsyncIterator[tuple[Orchestrator, RedisBus, Hub]]:
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'bus.db'}")
    await create_schema(engine)
    sessions = make_sessionmaker(engine)
    async with sessions.begin() as session:
        session.add(Investigation(id="inv", name="bus"))
    bus = RedisBus(fakeredis.FakeAsyncRedis(decode_responses=True))
    hub = Hub()
    orchestrator = Orchestrator(sessions, BusExecutor(bus, block_ms=0, poll_interval=0.01), hub)
    await orchestrator.start(watchdog_every=0.05)
    try:
        yield orchestrator, bus, hub
    finally:
        await orchestrator.stop()
        await engine.dispose()


async def start_workers(bus: RedisBus, *services) -> tuple[asyncio.Event, list[asyncio.Task]]:
    stop = asyncio.Event()
    workers = [
        asyncio.create_task(serve(service, bus, stop=stop, block_ms=0)) for service in services
    ]
    return stop, workers


async def wait_for(predicate) -> None:
    """Poll state that lives in Redis, for up to five seconds."""
    for _ in range(250):
        if await predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not met in time")


async def test_runs_over_redis_with_pivots(stack) -> None:
    orchestrator, bus, hub = stack
    stop, workers = await start_workers(bus, AvatarProfileService(), FakeHashService())

    async def registered() -> bool:
        infos = await orchestrator.executor.services()
        return {"avatar-profiles", "fake-hash"} <= {n for n, i in infos.items() if i.available}

    await wait_for(registered)
    async with hub.subscribe("inv") as queue:
        run = await orchestrator.start_run("inv", "alice", max_depth=1)
        assert run.services == ["avatar-profiles"]
        async with asyncio.timeout(5):
            await orchestrator.idle()
        messages = []
        while not queue.empty():
            messages.append(queue.get_nowait())
    stop.set()
    await asyncio.gather(*workers)

    completed = [m for m in messages if m["type"] == "run.completed"]
    assert completed[0]["status"] == RunStatus.COMPLETED
    groups = completed[0]["avatar_groups"]
    assert len(groups) == 1 and len(groups[0]["profiles"]) == 2
    async with orchestrator.sessions() as session:
        tasks = (await session.scalars(select(TaskRow))).all()
    assert sorted(t.service for t in tasks) == ["avatar-profiles"] + ["fake-hash"] * 3
    assert all(t.status == "completed" for t in tasks)


async def test_offline_services_are_not_planned_and_late_tasks_time_out(stack) -> None:
    orchestrator, bus, hub = stack
    stop, workers = await start_workers(bus, FakeService())

    async def registered() -> bool:
        return "fake" in await orchestrator.executor.services()

    await wait_for(registered)
    stop.set()
    await asyncio.gather(*workers)
    await bus.redis.delete(*[k async for k in bus.redis.scan_iter("deepsift:heartbeat:*")])

    infos = await orchestrator.executor.services()
    assert infos["fake"].state == "offline"
    assert await orchestrator.plan(EntityType.USERNAME) == []

    # Named explicitly, the task is queued; nobody answers, so the watchdog fails it.
    run = await orchestrator.start_run("inv", "alice", services=["fake"])
    task = next(iter(orchestrator._tasks.values()))
    task.deadline = now() - timedelta(seconds=1)
    async with asyncio.timeout(5):
        await orchestrator.idle()
    async with orchestrator.sessions() as session:
        row = (await session.scalars(select(TaskRow).where(TaskRow.run_id == run.id))).one()
    assert row.status == "failed"
    assert row.error["code"] == "timeout"


async def test_restart_marks_running_runs_interrupted(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'r.db'}")
    await create_schema(engine)
    sessions = make_sessionmaker(engine)
    async with sessions.begin() as session:
        session.add(Investigation(id="inv", name="x"))
        session.add(
            Run(id="run", investigation_id="inv", selector="a", type="username", entity_id="e")
        )
        session.add(TaskRow(id="task", run_id="run", service="fake", entity_id="e"))
    bus = RedisBus(fakeredis.FakeAsyncRedis(decode_responses=True))
    orchestrator = Orchestrator(sessions, BusExecutor(bus, block_ms=0), Hub())
    await orchestrator.start()
    await orchestrator.stop()
    async with sessions() as session:
        assert (await session.get(Run, "run")).status == RunStatus.INTERRUPTED
        assert (await session.get(TaskRow, "task")).status == "cancelled"
    await engine.dispose()
