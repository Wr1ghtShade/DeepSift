"""Local mode: run installed services in-process, without Redis or a gateway (section 9)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import Any

from .confidence import Level, combine, level
from .detect import detect_type
from .entities import Entity, EntityType
from .messages import Event, EventKind, Task
from .runner import execute
from .service import Service

ENTRY_POINT_GROUP = "deepsift.services"


def discover() -> dict[str, type[Service]]:
    """Services installed as Python packages, by manifest name."""
    found: dict[str, type[Service]] = {}
    for entry in entry_points(group=ENTRY_POINT_GROUP):
        cls = entry.load()
        found[cls.get_manifest().name] = cls
    return found


@dataclass
class Finding:
    """One entity, merged across the services that found it."""

    entity: Entity
    sources: dict[str, float] = field(default_factory=dict)

    @property
    def score(self) -> float:
        return combine(self.sources.values())

    @property
    def level(self) -> Level:
        return level(self.score)


class LocalRun:
    def __init__(self, services: Mapping[str, Service]) -> None:
        self.services = dict(services)
        self.input: Entity | None = None
        self._findings: dict[tuple[str, str], Finding] = {}

    @property
    def findings(self) -> list[Finding]:
        return sorted(self._findings.values(), key=lambda f: (-f.score, f.entity.value))

    def plan(self, entity_type: EntityType, only: list[str] | None = None) -> list[Service]:
        if only:
            unknown = sorted(set(only) - self.services.keys())
            if unknown:
                raise ValueError(f"unknown service(s): {', '.join(unknown)}")
            candidates = [self.services[name] for name in only]
        else:
            candidates = list(self.services.values())
        return [s for s in candidates if s.manifest.accepts(entity_type)]

    def _absorb(self, event: Event) -> None:
        if event.event is not EventKind.ENTITY or event.entity is None:
            return
        finding = self._findings.setdefault(event.entity.key, Finding(event.entity))
        previous = finding.sources.get(event.service, 0.0)
        finding.sources[event.service] = max(previous, event.entity.confidence)

    async def run(
        self,
        selector: str,
        entity_type: EntityType | None = None,
        only: list[str] | None = None,
        options: Mapping[str, dict[str, Any]] | None = None,
    ) -> AsyncIterator[Event]:
        """Run every matching service on the selector and yield events as they arrive."""
        entity_type = entity_type or detect_type(selector)
        self.input = Entity(type=entity_type, value=selector)
        services = self.plan(entity_type, only)
        options = options or {}
        queue: asyncio.Queue[Event] = asyncio.Queue()

        async def sink(event: Event) -> None:
            self._absorb(event)
            await queue.put(event)

        async def start(service: Service) -> None:
            await service.setup()
            name = service.manifest.name
            task = Task(service=name, input=self.input, options=options.get(name, {}))
            await execute(service, task, sink)

        jobs = [asyncio.create_task(start(service)) for service in services]
        pending = len(jobs)
        try:
            while pending:
                event = await queue.get()
                yield event
                if event.is_final:
                    pending -= 1
        finally:
            for job in jobs:
                job.cancel()
            await asyncio.gather(*jobs, return_exceptions=True)
