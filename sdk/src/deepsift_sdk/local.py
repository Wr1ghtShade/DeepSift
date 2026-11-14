"""Local mode: run installed services in-process, without Redis or a gateway (section 9).

Besides running services, the local run does what the gateway will do in the stack:

- **pivots** (section 6): an entity found by one service is handed to every service that
  accepts its type, up to ``max_depth`` hops from the selector;
- **merging**: entities with the same identity key become one finding, scored with a
  noisy-OR over the services that found it (section 13);
- **avatar groups**: profiles whose avatars have close perceptual hashes are grouped,
  and grouped profiles get the avatar bonus.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import Any

from .confidence import Level, combine, level, with_avatar_bonus
from .correlate import PHASH_THRESHOLD, group_avatars
from .detect import detect_type
from .entities import Entity, EntityType
from .messages import ErrorCode, ErrorInfo, Event, EventKind, Task
from .runner import execute
from .service import Service

ENTRY_POINT_GROUP = "deepsift.services"
MAX_DEPTH = 3

Key = tuple[str, str]


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
    avatar_group: str | None = None

    @property
    def score(self) -> float:
        base = combine(self.sources.values())
        grouped = self.avatar_group is not None and self.entity.type is EntityType.PROFILE
        return with_avatar_bonus(base, grouped)

    @property
    def level(self) -> Level:
        return level(self.score)


@dataclass(frozen=True)
class AvatarGroup:
    """Profiles on different sites that use the same picture."""

    name: str
    profiles: tuple[Key, ...]
    phashes: tuple[str, ...]


@dataclass(frozen=True)
class FoundLink:
    source: Key
    rel: str
    target: Key


class LocalRun:
    def __init__(
        self,
        services: Mapping[str, Service],
        max_depth: int = 1,
        enabled: set[str] | None = None,
    ) -> None:
        """``enabled`` turns on services whose manifest has ``enabled_by_default: false``."""
        if not 0 <= max_depth <= MAX_DEPTH:
            raise ValueError(f"max_depth must be between 0 and {MAX_DEPTH}")
        self.services = dict(services)
        self.max_depth = max_depth
        self.enabled = set(enabled or ())
        unknown = sorted(self.enabled - self.services.keys())
        if unknown:
            raise ValueError(f"unknown service(s): {', '.join(unknown)}")
        self._slots = {
            name: asyncio.Semaphore(service.manifest.concurrency)
            for name, service in self.services.items()
        }
        self.input: Entity | None = None
        self.avatar_groups: list[AvatarGroup] = []
        self._findings: dict[Key, Finding] = {}
        self._keys: dict[str, Key] = {}
        self._links: set[FoundLink] = set()
        self._ready: dict[str, asyncio.Task[None]] = {}

    @property
    def findings(self) -> list[Finding]:
        return sorted(self._findings.values(), key=lambda f: (-f.score, f.entity.value))

    @property
    def links(self) -> list[FoundLink]:
        return sorted(self._links, key=lambda link: (link.source, link.rel, link.target))

    def finding(self, key: Key) -> Finding | None:
        return self._findings.get(key)

    def is_enabled(self, name: str) -> bool:
        return self.services[name].manifest.enabled_by_default or name in self.enabled

    def plan(self, entity_type: EntityType, only: list[str] | None = None) -> list[Service]:
        """Services to run on an entity of this type.

        Opt-in services (``enabled_by_default: false``) run only when enabled, and
        services missing a required secret are skipped, unless enabled explicitly or
        named in ``only`` (then they run and report what is missing).
        """
        if only:
            unknown = sorted(set(only) - self.services.keys())
            if unknown:
                raise ValueError(f"unknown service(s): {', '.join(unknown)}")
            candidates = [self.services[name] for name in only]
        else:
            candidates = [
                s
                for name, s in self.services.items()
                if self.is_enabled(name)
                and (name in self.enabled or not s.manifest.missing_secrets())
            ]
        return [s for s in candidates if s.manifest.accepts(entity_type)]

    def _absorb(self, event: Event) -> None:
        if event.event is not EventKind.ENTITY or event.entity is None:
            return
        key = event.entity.key
        self._keys[event.entity.id] = key
        finding = self._findings.setdefault(key, Finding(event.entity))
        previous = finding.sources.get(event.service, 0.0)
        finding.sources[event.service] = max(previous, event.entity.confidence)
        if event.link is not None and event.link.from_ in self._keys:
            self._links.add(FoundLink(self._keys[event.link.from_], event.link.rel, key))

    def _correlate(self) -> None:
        """Group profiles whose avatars hash close together (pHash, Hamming distance)."""
        triples = [(link.source, link.rel, link.target) for link in self._links]
        attributes = {
            key: finding.entity.attributes
            for key, finding in self._findings.items()
            if finding.entity.type is EntityType.IMAGE_HASH
        }
        self.avatar_groups = []
        for name, profiles, hashes in group_avatars(triples, attributes, PHASH_THRESHOLD):
            self.avatar_groups.append(AvatarGroup(name, tuple(profiles), tuple(hashes)))
            for profile in profiles:
                self._findings[profile].avatar_group = name

    async def _setup(self, service: Service) -> None:
        name = service.manifest.name
        if name not in self._ready:
            self._ready[name] = asyncio.create_task(service.setup())
        await self._ready[name]

    async def run(
        self,
        selector: str,
        entity_type: EntityType | None = None,
        only: list[str] | None = None,
        options: Mapping[str, dict[str, Any]] | None = None,
    ) -> AsyncIterator[Event]:
        """Run matching services on the selector, then pivot, yielding events as they arrive.

        ``only`` restricts the services run on the selector itself; pivots may use any
        installed service.
        """
        entity_type = entity_type or detect_type(selector)
        self.input = Entity(type=entity_type, value=selector)
        self._keys[self.input.id] = self.input.key
        options = options or {}
        queue: asyncio.Queue[Event] = asyncio.Queue()
        jobs: list[asyncio.Task[None]] = []
        depth_of: dict[str, int] = {}
        seen: set[tuple[str, Key]] = set()
        pending = 0

        def spawn(service: Service, entity: Entity, depth: int) -> None:
            nonlocal pending
            name = service.manifest.name
            if (name, entity.key) in seen:
                return
            seen.add((name, entity.key))
            task = Task(service=name, input=entity, options=options.get(name, {}))
            depth_of[task.task_id] = depth
            pending += 1
            jobs.append(asyncio.create_task(start(service, task)))

        async def sink(event: Event) -> None:
            self._absorb(event)
            depth = depth_of.get(event.task_id, 0)
            if event.event is EventKind.ENTITY and event.entity and depth < self.max_depth:
                for service in self.plan(event.entity.type):  # pivots honour opt-in
                    spawn(service, event.entity, depth + 1)
            await queue.put(event)

        async def start(service: Service, task: Task) -> None:
            try:
                await self._setup(service)
            except Exception as exc:  # a broken service must not stall the whole run
                error = ErrorInfo.of(ErrorCode.INTERNAL, f"setup failed: {type(exc).__name__}")
                await sink(
                    Event(task_id=task.task_id, service=task.service, event=EventKind.STARTED)
                )
                await sink(
                    Event(
                        task_id=task.task_id,
                        service=task.service,
                        event=EventKind.FAILED,
                        error=error,
                    )
                )
                return
            async with self._slots[service.manifest.name]:
                await execute(service, task, sink)

        for service in self.plan(entity_type, only):
            spawn(service, self.input, 0)
        try:
            while pending:
                event = await queue.get()
                yield event
                if event.is_final:
                    pending -= 1
            self._correlate()
        finally:
            for job in jobs:
                job.cancel()
            await asyncio.gather(*jobs, return_exceptions=True)
