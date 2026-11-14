"""The interface every bus implements (contract sections 4 and 5)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..manifest import Manifest
from ..messages import Event, Task


@dataclass(frozen=True)
class Delivery:
    """A task handed to a worker. Acknowledge it once its final event is sent."""

    message_id: str
    task: Task


class Bus(Protocol):
    async def publish_task(self, task: Task) -> None: ...

    async def publish_event(self, event: Event) -> None: ...

    async def read_tasks(
        self, service: str, consumer: str, count: int, block_ms: int
    ) -> list[Delivery]: ...

    async def ack(self, service: str, delivery: Delivery) -> None: ...

    async def register(self, manifest: Manifest, instance_id: str, state: str) -> None: ...

    async def deregister(self, manifest: Manifest, instance_id: str) -> None: ...

    async def heartbeat(
        self,
        service: str,
        instance_id: str,
        state: str,
        running: int,
        ttl: int,
        missing: list[str] | None = None,
    ) -> None: ...
