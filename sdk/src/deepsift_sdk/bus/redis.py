"""Redis Streams bus (contract sections 4 and 5).

Streams, all prefixed with ``deepsift:``:

- ``tasks:<service>``: tasks, read through the consumer group ``<service>``
- ``events``: events from all services, read by the gateway
- ``registry``: register and deregister events with manifests
- ``heartbeat:<service>:<instance>``: plain keys with a TTL
"""

from __future__ import annotations

import json

from redis import asyncio as aioredis
from redis.exceptions import ResponseError

from ..manifest import Manifest
from ..messages import Event, Task
from .base import Delivery

EVENTS_MAXLEN = 100_000


class RedisBus:
    def __init__(self, client: aioredis.Redis, prefix: str = "deepsift") -> None:
        self.redis = client
        self.prefix = prefix
        self._groups: set[str] = set()

    @classmethod
    def from_url(cls, url: str, prefix: str = "deepsift") -> RedisBus:
        return cls(aioredis.from_url(url, decode_responses=True), prefix)

    def _key(self, *parts: str) -> str:
        return ":".join((self.prefix, *parts))

    async def close(self) -> None:
        await self.redis.aclose()

    async def ensure_group(self, service: str) -> None:
        if service in self._groups:
            return
        try:
            await self.redis.xgroup_create(
                self._key("tasks", service), service, id="0", mkstream=True
            )
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise
        self._groups.add(service)

    async def publish_task(self, task: Task) -> None:
        await self.redis.xadd(
            self._key("tasks", task.service), {"data": task.model_dump_json(by_alias=True)}
        )

    async def publish_event(self, event: Event) -> None:
        await self.redis.xadd(
            self._key("events"),
            {"data": event.to_json()},
            maxlen=EVENTS_MAXLEN,
            approximate=True,
        )

    async def read_tasks(
        self, service: str, consumer: str, count: int, block_ms: int
    ) -> list[Delivery]:
        """Read new tasks for this consumer. ``block_ms <= 0`` returns at once."""
        await self.ensure_group(service)
        response = await self.redis.xreadgroup(
            service,
            consumer,
            {self._key("tasks", service): ">"},
            count=count,
            block=block_ms if block_ms > 0 else None,
        )
        deliveries = []
        for _stream, messages in response or []:
            for message_id, fields in messages:
                deliveries.append(Delivery(message_id, Task.model_validate_json(fields["data"])))
        return deliveries

    async def claim_stale(
        self, service: str, consumer: str, min_idle_ms: int, count: int = 10
    ) -> list[Delivery]:
        """Take over tasks left pending by a worker that died (XAUTOCLAIM)."""
        await self.ensure_group(service)
        result = await self.redis.xautoclaim(
            self._key("tasks", service), service, consumer, min_idle_ms, "0-0", count=count
        )
        messages = result[1] if result else []
        return [
            Delivery(message_id, Task.model_validate_json(fields["data"]))
            for message_id, fields in messages
            if fields
        ]

    async def ack(self, service: str, delivery: Delivery) -> None:
        await self.redis.xack(self._key("tasks", service), service, delivery.message_id)

    async def read_events(
        self, last_id: str = "$", count: int = 100, block_ms: int = 1000
    ) -> list[tuple[str, Event]]:
        response = await self.redis.xread(
            {self._key("events"): last_id}, count=count, block=block_ms if block_ms > 0 else None
        )
        return [
            (message_id, Event.model_validate_json(fields["data"]))
            for _stream, messages in response or []
            for message_id, fields in messages
        ]

    async def register(self, manifest: Manifest, instance_id: str, state: str) -> None:
        await self.redis.xadd(
            self._key("registry"),
            {
                "event": "register",
                "service": manifest.name,
                "instance": instance_id,
                "state": state,
                "manifest": manifest.model_dump_json(),
            },
        )

    async def deregister(self, manifest: Manifest, instance_id: str) -> None:
        await self.redis.xadd(
            self._key("registry"),
            {"event": "deregister", "service": manifest.name, "instance": instance_id},
        )

    async def heartbeat(
        self, service: str, instance_id: str, state: str, running: int, ttl: int
    ) -> None:
        await self.redis.set(
            self._key("heartbeat", service, instance_id),
            json.dumps({"state": state, "running": running}),
            ex=ttl,
        )
