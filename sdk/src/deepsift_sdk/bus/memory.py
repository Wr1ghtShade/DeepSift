"""In-process bus with the same semantics as the Redis one. For tests and local mode."""

from __future__ import annotations

import asyncio
import itertools
from collections import defaultdict

from ..manifest import Manifest
from ..messages import Event, Task
from .base import Delivery


class MemoryBus:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Queue[Delivery]] = defaultdict(asyncio.Queue)
        self._ids = itertools.count(1)
        self.events: asyncio.Queue[Event] = asyncio.Queue()
        self.registry: dict[str, dict] = {}
        self.heartbeats: dict[tuple[str, str], dict] = {}
        self.acked: list[str] = []

    async def publish_task(self, task: Task) -> None:
        await self._tasks[task.service].put(Delivery(str(next(self._ids)), task))

    async def publish_event(self, event: Event) -> None:
        await self.events.put(event)

    async def read_tasks(
        self, service: str, consumer: str, count: int, block_ms: int
    ) -> list[Delivery]:
        queue = self._tasks[service]
        try:
            first = await asyncio.wait_for(queue.get(), timeout=block_ms / 1000)
        except TimeoutError:
            return []
        batch = [first]
        while len(batch) < count and not queue.empty():
            batch.append(queue.get_nowait())
        return batch

    async def ack(self, service: str, delivery: Delivery) -> None:
        self.acked.append(delivery.message_id)

    async def register(self, manifest: Manifest, instance_id: str, state: str) -> None:
        self.registry[manifest.name] = {"manifest": manifest, "state": state}

    async def deregister(self, manifest: Manifest, instance_id: str) -> None:
        self.registry.pop(manifest.name, None)

    async def heartbeat(
        self, service: str, instance_id: str, state: str, running: int, ttl: int
    ) -> None:
        self.heartbeats[(service, instance_id)] = {"state": state, "running": running}
