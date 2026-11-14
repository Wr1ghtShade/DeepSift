"""Where tasks run.

- :class:`LocalExecutor` runs installed services inside the gateway process. It suits a
  single-user install (``pipx install deepsift-gateway[services]``) with no Redis.
- :class:`BusExecutor` sends tasks to service workers over Redis Streams (contract
  sections 4 and 5) and reads their events and registrations back.

Both report services the same way, so the orchestrator and the API do not care which
one is in use.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

from deepsift_sdk.bus.redis import RedisBus
from deepsift_sdk.manifest import Manifest
from deepsift_sdk.messages import ErrorCode, ErrorInfo, Event, EventKind, Task
from deepsift_sdk.runner import execute
from deepsift_sdk.service import Service
from pydantic import ValidationError

log = logging.getLogger(__name__)

EventHandler = Callable[[Event], Awaitable[None]]


@dataclass(frozen=True)
class Instance:
    id: str
    state: str
    running: int = 0
    missing: tuple[str, ...] = ()


@dataclass
class ServiceInfo:
    """A service as the gateway sees it.

    ``state``: ``ready``, ``busy``, ``needs_config`` or ``offline``.
    """

    manifest: Manifest
    state: str
    instances: list[Instance] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return self.state in ("ready", "busy")


class Executor(Protocol):
    async def start(self, on_event: EventHandler) -> None: ...

    async def stop(self) -> None: ...

    async def submit(self, task: Task) -> None: ...

    async def cancel(self, task_ids: Iterable[str]) -> None: ...

    async def services(self) -> dict[str, ServiceInfo]: ...


class LocalExecutor:
    def __init__(self, services: Mapping[str, Service]) -> None:
        self._services = dict(services)
        self._slots = {
            name: asyncio.Semaphore(service.manifest.concurrency)
            for name, service in self._services.items()
        }
        self._running = dict.fromkeys(self._services, 0)
        self._ready: dict[str, asyncio.Task[None]] = {}
        self._jobs: dict[str, asyncio.Task[None]] = {}
        self._on_event: EventHandler | None = None

    async def start(self, on_event: EventHandler) -> None:
        self._on_event = on_event

    async def stop(self) -> None:
        jobs = list(self._jobs.values())
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
        for service in self._services.values():
            with contextlib.suppress(Exception):
                await service.close()

    async def _setup(self, service: Service) -> None:
        name = service.manifest.name
        if name not in self._ready:
            self._ready[name] = asyncio.create_task(service.setup())
        await self._ready[name]

    async def _run(self, task: Task) -> None:
        assert self._on_event is not None
        sink = self._on_event
        service = self._services.get(task.service)
        if service is None:
            await sink(Event(task_id=task.task_id, service=task.service, event=EventKind.STARTED))
            error = ErrorInfo.of(ErrorCode.INTERNAL, "service not installed")
            await sink(
                Event(
                    task_id=task.task_id, service=task.service, event=EventKind.FAILED, error=error
                )
            )
            return
        try:
            await self._setup(service)
        except Exception as exc:  # noqa: BLE001 - a broken service must not stall a run
            await sink(Event(task_id=task.task_id, service=task.service, event=EventKind.STARTED))
            error = ErrorInfo.of(ErrorCode.INTERNAL, f"setup failed: {type(exc).__name__}")
            await sink(
                Event(
                    task_id=task.task_id, service=task.service, event=EventKind.FAILED, error=error
                )
            )
            return
        async with self._slots[task.service]:
            self._running[task.service] += 1
            try:
                await execute(service, task, sink)
            finally:
                self._running[task.service] -= 1

    async def submit(self, task: Task) -> None:
        job = asyncio.create_task(self._run(task))
        self._jobs[task.task_id] = job
        job.add_done_callback(lambda _: self._jobs.pop(task.task_id, None))

    async def cancel(self, task_ids: Iterable[str]) -> None:
        jobs = [self._jobs[t] for t in task_ids if t in self._jobs]
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)

    async def services(self) -> dict[str, ServiceInfo]:
        result = {}
        for name, service in self._services.items():
            try:
                extra = await service.missing_setup()
            except Exception:  # noqa: BLE001
                extra = ["setup check failed: see the gateway logs"]
            missing = [*service.manifest.missing_secrets(), *extra]
            running = self._running[name]
            busy = running >= service.manifest.concurrency
            state = "needs_config" if missing else ("busy" if busy else "ready")
            result[name] = ServiceInfo(
                manifest=service.manifest,
                state=state,
                instances=[Instance("local", state, running)],
                missing=missing,
            )
        return result


class BusExecutor:
    """Tasks out to Redis, events and registrations in from Redis.

    ``block_ms`` is how long one read waits for new messages; ``0`` polls instead (tests).
    """

    def __init__(self, bus: RedisBus, block_ms: int = 1000, poll_interval: float = 0.05) -> None:
        self.bus = bus
        self.block_ms = block_ms
        self.poll_interval = poll_interval
        self._manifests: dict[str, Manifest] = {}
        self._instances: dict[str, set[str]] = {}
        self._loop: asyncio.Task[None] | None = None
        self._on_event: EventHandler | None = None
        self._stopping = False

    def _key(self, *parts: str) -> str:
        return self.bus._key(*parts)  # noqa: SLF001 - same package family

    async def start(self, on_event: EventHandler) -> None:
        self._on_event = on_event
        last = await self.bus.redis.xrevrange(self._key("events"), count=1)
        events_from = last[0][0] if last else "0-0"
        self._loop = asyncio.create_task(self._consume(events_from))

    async def stop(self) -> None:
        # Some Redis client versions swallow a cancellation that lands mid-read, so
        # the loop also checks a flag, and the wait is bounded.
        self._stopping = True
        if self._loop is not None:
            self._loop.cancel()
            with contextlib.suppress(asyncio.CancelledError, TimeoutError):
                await asyncio.wait_for(self._loop, timeout=self.block_ms / 1000 + 2)

    def _registry_message(self, fields: Mapping[str, str]) -> None:
        name = fields.get("service", "")
        instance = fields.get("instance", "")
        if fields.get("event") == "register":
            try:
                self._manifests[name] = Manifest.model_validate_json(fields["manifest"])
            except (KeyError, ValidationError):
                log.warning("ignored an invalid registration for %r", name)
                return
            self._instances.setdefault(name, set()).add(instance)
        elif fields.get("event") == "deregister":
            self._instances.get(name, set()).discard(instance)

    async def _consume(self, events_from: str) -> None:
        streams = {self._key("events"): events_from, self._key("registry"): "0-0"}
        block = self.block_ms if self.block_ms > 0 else None
        while not self._stopping:
            try:
                response = await self.bus.redis.xread(streams, count=200, block=block)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - Redis restarts must not kill the gateway
                log.exception("reading from Redis failed, retrying")
                await asyncio.sleep(1.0)
                continue
            if not response:
                if block is None:
                    await asyncio.sleep(self.poll_interval)
                continue
            for stream, messages in response:
                for message_id, fields in messages:
                    streams[stream] = message_id
                    if stream == self._key("registry"):
                        self._registry_message(fields)
                        continue
                    try:
                        event = Event.model_validate_json(fields["data"])
                    except (KeyError, ValidationError):
                        log.warning("ignored an invalid event %s", message_id)
                        continue
                    try:
                        assert self._on_event is not None
                        await self._on_event(event)
                    except Exception:  # noqa: BLE001 - one bad event must not stop the loop
                        log.exception("handling event %s failed", message_id)

    async def submit(self, task: Task) -> None:
        await self.bus.publish_task(task)

    async def cancel(self, task_ids: Iterable[str]) -> None:
        """Workers cannot be interrupted; the orchestrator ignores later events instead."""

    async def _heartbeats(self) -> dict[str, list[Instance]]:
        found: dict[str, list[Instance]] = {}
        prefix = self._key("heartbeat") + ":"
        keys = [key async for key in self.bus.redis.scan_iter(match=prefix + "*", count=200)]
        values = await self.bus.redis.mget(keys) if keys else []
        for key, raw in zip(keys, values, strict=True):
            if raw is None:
                continue
            service, _, instance = key[len(prefix) :].partition(":")
            try:
                data = json.loads(raw)
            except ValueError:
                continue
            raw_missing = data.get("missing") or []
            found.setdefault(service, []).append(
                Instance(
                    instance,
                    str(data.get("state", "ready")),
                    int(data.get("running", 0)),
                    tuple(str(m) for m in raw_missing if isinstance(m, str))[:10],
                )
            )
        return found

    async def services(self) -> dict[str, ServiceInfo]:
        beats = await self._heartbeats()
        result = {}
        for name, manifest in self._manifests.items():
            instances = sorted(beats.get(name, []), key=lambda i: i.id)
            states = {i.state for i in instances}
            if not instances:
                state = "offline"
            elif states & {"ready", "busy"}:
                state = "ready" if "ready" in states else "busy"
            else:
                state = "needs_config"
            missing = (
                sorted({m for i in instances for m in i.missing}) if state == "needs_config" else []
            )
            result[name] = ServiceInfo(
                manifest=manifest, state=state, instances=instances, missing=missing
            )
        return result
