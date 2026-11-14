"""Worker loop: serve one service over a bus.

Run a containerised service with::

    python -m deepsift_sdk.worker deepsift_svc_sherlock:SherlockService

The bus URL comes from ``REDIS_URL`` (default ``redis://localhost:6379/0``).
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import os
import signal
import socket
import sys
import time

from .bus.base import Bus, Delivery
from .ids import new_id
from .runner import execute
from .service import Service

log = logging.getLogger("deepsift.worker")

HEARTBEAT_EVERY = 15
HEARTBEAT_TTL = 45


async def serve(
    service: Service,
    bus: Bus,
    *,
    instance_id: str | None = None,
    stop: asyncio.Event | None = None,
    block_ms: int = 1000,
) -> None:
    manifest = service.manifest
    instance = instance_id or f"{socket.gethostname()}-{new_id()[-6:].lower()}"
    stop = stop or asyncio.Event()
    running: set[asyncio.Task[None]] = set()
    slots = asyncio.Semaphore(manifest.concurrency)
    claim_stale = getattr(bus, "claim_stale", None)
    last_claim = time.monotonic()

    async def missing() -> list[str]:
        """Secrets and setup steps still missing; checked again with every heartbeat."""
        try:
            extra = await service.missing_setup()
        except Exception:  # noqa: BLE001 - a failing check means "not ready"
            log.exception("%s: missing_setup() failed", manifest.name)
            extra = ["setup check failed: see the service logs"]
        return [*manifest.missing_secrets(), *extra]

    await service.setup()
    todo = await missing()
    ready = asyncio.Event()
    if not todo:
        ready.set()
    state = "ready" if ready.is_set() else "needs_config"
    await bus.register(manifest, instance, state)
    log.info("%s %s registered as %s (%s)", manifest.name, manifest.version, instance, state)

    async def beat() -> None:
        nonlocal todo
        while not stop.is_set():
            if not ready.is_set():
                todo = await missing()
                if not todo:
                    log.info("%s is configured; taking tasks", manifest.name)
                    ready.set()
            current = "busy" if running else ("ready" if ready.is_set() else "needs_config")
            await bus.heartbeat(manifest.name, instance, current, len(running), HEARTBEAT_TTL, todo)
            try:
                await asyncio.wait_for(stop.wait(), HEARTBEAT_EVERY)
            except TimeoutError:
                pass

    async def handle(delivery: Delivery) -> None:
        try:
            await execute(service, delivery.task, bus.publish_event)
            await bus.ack(manifest.name, delivery)
        finally:
            slots.release()

    beat_task = asyncio.create_task(beat())
    try:
        if not ready.is_set():
            log.warning("%s needs configuration (%s); waiting", manifest.name, ", ".join(todo))
            waiter = asyncio.create_task(ready.wait())
            stopper = asyncio.create_task(stop.wait())
            await asyncio.wait({waiter, stopper}, return_when=asyncio.FIRST_COMPLETED)
            waiter.cancel()
            stopper.cancel()
        while not stop.is_set():
            await slots.acquire()
            deliveries = await bus.read_tasks(manifest.name, instance, 1, block_ms)
            if not deliveries and claim_stale and time.monotonic() - last_claim > manifest.timeout:
                last_claim = time.monotonic()
                stale_ms = int((manifest.timeout + 30) * 1000)
                deliveries = await claim_stale(manifest.name, instance, stale_ms, 1)
            if not deliveries:
                slots.release()
                if block_ms <= 0:
                    await asyncio.sleep(0.01)
                continue
            for delivery in deliveries:
                job = asyncio.create_task(handle(delivery))
                running.add(job)
                job.add_done_callback(running.discard)
    finally:
        if running:
            await asyncio.gather(*running, return_exceptions=True)
        stop.set()
        beat_task.cancel()
        await bus.deregister(manifest, instance)
        await service.close()


def load_service(target: str) -> Service:
    """Instantiate a service from 'package.module:ClassName'."""
    module_name, _, class_name = target.partition(":")
    if not class_name:
        raise SystemExit("usage: python -m deepsift_sdk.worker package.module:ServiceClass")
    cls = getattr(importlib.import_module(module_name), class_name)
    return cls()


async def _main(target: str) -> None:
    from .bus.redis import RedisBus

    service = load_service(target)
    bus = RedisBus.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        await serve(service, bus, stop=stop)
    finally:
        await bus.close()


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m deepsift_sdk.worker package.module:ServiceClass")
    asyncio.run(_main(sys.argv[1]))


if __name__ == "__main__":
    main()
