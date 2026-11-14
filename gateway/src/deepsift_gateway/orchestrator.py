"""Runs, tasks, merging, pivots and correlation: the gateway's side of the contract.

Every event from a service goes through :meth:`Orchestrator.handle_event`, one at a time
(a lock keeps database writes and pivot decisions in order). Entities are merged per
investigation on their identity key; each run pivots on what it finds up to its
``max_depth``; when a run's last task ends, avatar groups are recomputed over the whole
investigation.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from deepsift_sdk.confidence import combine, level, with_avatar_bonus
from deepsift_sdk.correlate import group_avatars
from deepsift_sdk.detect import detect_type
from deepsift_sdk.entities import Entity, EntityType
from deepsift_sdk.ids import new_id
from deepsift_sdk.local import MAX_DEPTH
from deepsift_sdk.manifest import Manifest
from deepsift_sdk.messages import ErrorCode, ErrorInfo, Event, EventKind, Task
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .db import (
    EntityRow,
    LinkRow,
    Run,
    RunStatus,
    ServiceSetting,
    SourceRow,
    TaskRow,
    TaskStatus,
    iso,
    now,
)
from .executors import Executor, ServiceInfo
from .hub import Hub

log = logging.getLogger(__name__)

#: Extra time on top of the manifest timeout and its retries before a task is given up.
DEADLINE_MARGIN = timedelta(seconds=60)
MAX_RETRIES = 2
MAX_OPTION_LENGTH = 256


class RunError(ValueError):
    """A run request the gateway cannot accept (unknown service, bad option…)."""


@dataclass
class ActiveTask:
    run_id: str
    investigation_id: str
    service: str
    depth: int
    deadline: datetime


@dataclass
class ActiveRun:
    id: str
    investigation_id: str
    max_depth: int
    options: dict[str, dict[str, Any]]
    pending: set[str] = field(default_factory=set)
    seen: set[tuple[str, tuple[str, str]]] = field(default_factory=set)
    #: entity ids used by services in this run -> database ids
    ids: dict[str, str] = field(default_factory=dict)


def entity_out(row: EntityRow, sources: list[SourceRow]) -> dict[str, Any]:
    return {
        "id": row.id,
        "type": row.type,
        "value": row.value,
        "attributes": row.attributes,
        "score": row.score,
        "level": level(row.score).value,
        "selector": row.selector,
        "avatar_group": row.avatar_group,
        "first_seen": iso(row.first_seen),
        "sources": [
            {"service": s.service, "confidence": s.confidence}
            for s in sorted(sources, key=lambda s: (-s.confidence, s.service))
        ],
    }


def run_out(run: Run) -> dict[str, Any]:
    return {
        "id": run.id,
        "investigation_id": run.investigation_id,
        "selector": run.selector,
        "type": run.type,
        "entity_id": run.entity_id,
        "services": run.services,
        "max_depth": run.max_depth,
        "status": run.status,
        "created_at": iso(run.created_at),
        "finished_at": iso(run.finished_at),
    }


def task_out(row: TaskRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "service": row.service,
        "entity_id": row.entity_id,
        "depth": row.depth,
        "status": row.status,
        "done": row.done,
        "total": row.total,
        "count": row.count,
        "error": row.error,
    }


def score_of(row: EntityRow, sources: list[SourceRow]) -> float:
    base = combine(s.confidence for s in sources)
    grouped = row.avatar_group is not None and row.type == EntityType.PROFILE.value
    return with_avatar_bonus(base, grouped)


def check_options(
    options: Mapping[str, Any] | None, manifests: Mapping[str, Manifest]
) -> dict[str, dict[str, Any]]:
    """Validate ``{service: {option: value}}`` against the manifests and coerce types."""
    checked: dict[str, dict[str, Any]] = {}
    for service, values in (options or {}).items():
        manifest = manifests.get(service)
        if manifest is None:
            raise RunError(f"options for unknown service {service!r}")
        if not isinstance(values, Mapping):
            raise RunError(f"options for {service} must be an object")
        checked[service] = {}
        for name, value in values.items():
            spec = manifest.options.get(name)
            if spec is None:
                raise RunError(f"{service} has no option {name!r}")
            if spec.type == "bool" and isinstance(value, bool):
                coerced: Any = value
            elif spec.type == "int" and isinstance(value, int) and not isinstance(value, bool):
                coerced = value
            elif spec.type in ("str", "enum") and isinstance(value, str):
                if len(value) > MAX_OPTION_LENGTH:
                    raise RunError(f"{service}.{name} is too long")
                coerced = value
            else:
                raise RunError(f"{service}.{name} must be of type {spec.type}")
            if spec.type == "enum" and spec.values and coerced not in spec.values:
                allowed = ", ".join(map(str, spec.values))
                raise RunError(f"{service}.{name} must be one of: {allowed}")
            checked[service][name] = coerced
    return checked


class Orchestrator:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], executor: Executor, hub: Hub
    ) -> None:
        self.sessions = sessions
        self.executor = executor
        self.hub = hub
        self._lock = asyncio.Lock()
        self._runs: dict[str, ActiveRun] = {}
        self._tasks: dict[str, ActiveTask] = {}
        self._watchdog: asyncio.Task[None] | None = None
        self._quiet = asyncio.Event()
        self._quiet.set()

    def _changed(self) -> None:
        if self._runs:
            self._quiet.clear()
        else:
            self._quiet.set()

    # -- lifecycle -----------------------------------------------------------------

    async def start(self, watchdog_every: float = 5.0) -> None:
        await self._recover()
        await self.executor.start(self.handle_event)
        self._watchdog = asyncio.create_task(self._watch(watchdog_every))

    async def stop(self) -> None:
        if self._watchdog is not None:
            self._watchdog.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._watchdog
        await self.executor.stop()

    async def _recover(self) -> None:
        """Runs cut short by a restart are marked interrupted."""
        async with self.sessions.begin() as session:
            stale = select(Run.id).where(Run.status == RunStatus.RUNNING)
            await session.execute(
                update(TaskRow)
                .where(TaskRow.run_id.in_(stale), TaskRow.status.not_in(TaskStatus.FINAL))
                .values(status=TaskStatus.CANCELLED, finished_at=now())
            )
            await session.execute(
                update(Run)
                .where(Run.status == RunStatus.RUNNING)
                .values(status=RunStatus.INTERRUPTED, finished_at=now())
            )

    async def _watch(self, every: float) -> None:
        while True:
            await asyncio.sleep(every)
            late = [
                (task_id, task)
                for task_id, task in list(self._tasks.items())
                if task.deadline < now()
            ]
            for task_id, task in late:
                error = ErrorInfo.of(ErrorCode.TIMEOUT, "no answer from the service")
                await self.handle_event(
                    Event(
                        task_id=task_id, service=task.service, event=EventKind.FAILED, error=error
                    )
                )

    # -- services ------------------------------------------------------------------

    async def service_settings(self) -> dict[str, bool]:
        async with self.sessions() as session:
            rows = (await session.scalars(select(ServiceSetting))).all()
        return {row.name: row.enabled for row in rows}

    async def set_enabled(self, name: str, enabled: bool) -> None:
        async with self.sessions.begin() as session:
            await session.merge(ServiceSetting(name=name, enabled=enabled))

    async def services(self) -> tuple[dict[str, ServiceInfo], dict[str, bool]]:
        infos = await self.executor.services()
        settings = await self.service_settings()
        enabled = {
            name: settings.get(name, info.manifest.enabled_by_default)
            for name, info in infos.items()
        }
        return infos, enabled

    async def plan(self, entity_type: EntityType, only: list[str] | None = None) -> list[str]:
        """Services to run on an entity of this type.

        Without ``only``: enabled services with a live, configured instance. Services
        named in ``only`` run even if disabled; they report what they lack.
        """
        infos, enabled = await self.services()
        if only:
            unknown = sorted(set(only) - infos.keys())
            if unknown:
                raise RunError(f"unknown service(s): {', '.join(unknown)}")
            refused = [n for n in only if not infos[n].manifest.accepts(entity_type)]
            if refused:
                raise RunError(f"{', '.join(refused)} cannot take a {entity_type.value}")
            return list(dict.fromkeys(only))
        return sorted(
            name
            for name, info in infos.items()
            if enabled[name] and info.available and info.manifest.accepts(entity_type)
        )

    # -- runs ----------------------------------------------------------------------

    async def start_run(
        self,
        investigation_id: str,
        selector: str,
        entity_type: EntityType | None = None,
        services: list[str] | None = None,
        options: Mapping[str, Any] | None = None,
        max_depth: int = 0,
        mark_selector: bool = True,
    ) -> Run:
        if not 0 <= max_depth <= MAX_DEPTH:
            raise RunError(f"max_depth must be between 0 and {MAX_DEPTH}")
        entity_type = entity_type or detect_type(selector)
        try:
            entity = Entity(type=entity_type, value=selector)
        except ValueError as exc:
            raise RunError("empty selector") from exc
        infos = await self.executor.services()
        checked = check_options(options, {n: i.manifest for n, i in infos.items()})
        names = await self.plan(entity_type, services)

        async with self._lock:
            async with self.sessions.begin() as session:
                row, _ = await self._upsert_entity(session, investigation_id, entity, None)
                if mark_selector and not row.selector:
                    row.selector = True
                run = Run(
                    investigation_id=investigation_id,
                    selector=entity.value,
                    type=entity_type.value,
                    entity_id=row.id,
                    services=names,
                    options=checked,
                    max_depth=max_depth,
                )
                session.add(run)
                await session.flush()
                active = ActiveRun(run.id, investigation_id, max_depth, checked)
                active.ids[entity.id] = row.id
                self._runs[run.id] = active
                self._changed()
                tasks = [
                    self._new_task(session, active, infos, name, entity, row.id, 0)
                    for name in names
                ]
                tasks = [t for t in tasks if t is not None]
                if not tasks:
                    run.status = RunStatus.COMPLETED
                    run.finished_at = now()
                    del self._runs[run.id]
                    self._changed()
            self.hub.publish(investigation_id, {"type": "run.started", "run": run_out(run)})
            await self._dispatch(investigation_id, tasks)
            if not tasks:
                self.hub.publish(
                    investigation_id,
                    {"type": "run.completed", "run_id": run.id, "status": run.status},
                )
        return run

    def _new_task(
        self,
        session: AsyncSession,
        run: ActiveRun,
        infos: Mapping[str, ServiceInfo],
        service: str,
        entity: Entity,
        entity_row_id: str,
        depth: int,
    ) -> tuple[Task, TaskRow] | None:
        if (service, entity.key) in run.seen:
            return None
        run.seen.add((service, entity.key))
        manifest = infos[service].manifest
        allowed = manifest.timeout * (MAX_RETRIES + 1)
        deadline = now() + timedelta(seconds=allowed) + DEADLINE_MARGIN
        task = Task(
            run_id=run.id,
            investigation_id=run.investigation_id,
            service=service,
            input=entity,
            options=run.options.get(service, {}),
            deadline=deadline,
        )
        row = TaskRow(
            id=task.task_id, run_id=run.id, service=service, entity_id=entity_row_id, depth=depth
        )
        session.add(row)
        run.pending.add(task.task_id)
        self._tasks[task.task_id] = ActiveTask(
            run.id, run.investigation_id, service, depth, deadline
        )
        return task, row

    async def _dispatch(self, investigation_id: str, tasks: list[tuple[Task, TaskRow]]) -> None:
        for task, row in tasks:
            self.hub.publish(investigation_id, {"type": "task.queued", "task": task_out(row)})
            await self.executor.submit(task)

    async def cancel_run(self, run_id: str) -> bool:
        """Stop a run. Returns False if it was not running."""
        async with self._lock:
            active = self._runs.pop(run_id, None)
            self._changed()
            if active is None:
                return False
            task_ids = list(active.pending)
            for task_id in task_ids:
                self._tasks.pop(task_id, None)
            async with self.sessions.begin() as session:
                await session.execute(
                    update(TaskRow)
                    .where(TaskRow.run_id == run_id, TaskRow.status.not_in(TaskStatus.FINAL))
                    .values(status=TaskStatus.CANCELLED, finished_at=now())
                )
                await session.execute(
                    update(Run)
                    .where(Run.id == run_id)
                    .values(status=RunStatus.CANCELLED, finished_at=now())
                )
        await self.executor.cancel(task_ids)
        self.hub.publish(
            active.investigation_id,
            {"type": "run.completed", "run_id": run_id, "status": RunStatus.CANCELLED},
        )
        return True

    def is_running(self, run_id: str) -> bool:
        return run_id in self._runs

    async def idle(self) -> None:
        """Wait until no run is active (tests and graceful shutdown)."""
        await self._quiet.wait()

    # -- events --------------------------------------------------------------------

    async def _upsert_entity(
        self,
        session: AsyncSession,
        investigation_id: str,
        entity: Entity,
        source: tuple[str, str] | None,
    ) -> tuple[EntityRow, bool]:
        """Insert or merge an entity; ``source`` is (service, task_id). Returns (row, new)."""
        row = await session.scalar(
            select(EntityRow).where(
                EntityRow.investigation_id == investigation_id,
                EntityRow.type == entity.type.value,
                EntityRow.value == entity.value,
            )
        )
        created = row is None
        if row is None:
            row = EntityRow(
                id="ent_" + new_id(),  # never trust ids chosen by a service
                investigation_id=investigation_id,
                type=entity.type.value,
                value=entity.value,
                attributes=dict(entity.attributes),
                score=0.0,
            )
            session.add(row)
            await session.flush()
        elif entity.attributes:
            merged = dict(row.attributes)
            merged.update({k: v for k, v in entity.attributes.items() if v is not None})
            row.attributes = merged
        if source is not None:
            service, task_id = source
            existing = await session.get(SourceRow, (row.id, service))
            if existing is None:
                session.add(
                    SourceRow(
                        entity_id=row.id,
                        service=service,
                        confidence=entity.confidence,
                        task_id=task_id,
                    )
                )
            elif entity.confidence > existing.confidence:
                existing.confidence = entity.confidence
            await session.flush()
            sources = (
                await session.scalars(select(SourceRow).where(SourceRow.entity_id == row.id))
            ).all()
            row.score = score_of(row, list(sources))
        return row, created

    async def handle_event(self, event: Event) -> None:
        async with self._lock:
            task = self._tasks.get(event.task_id)
            if task is None:
                return  # unknown, finished or cancelled
            run = self._runs[task.run_id]
            messages: list[dict[str, Any]] = []
            spawned: list[tuple[Task, TaskRow]] = []
            async with self.sessions.begin() as session:
                row = await session.get(TaskRow, event.task_id)
                if row is None:
                    return
                base = {"run_id": run.id, "task_id": row.id, "service": row.service}
                match event.event:
                    case EventKind.STARTED:
                        row.status = TaskStatus.RUNNING
                        messages.append({"type": "task.started", **base})
                    case EventKind.PROGRESS:
                        row.done, row.total = event.done, event.total
                        messages.append(
                            {
                                "type": "task.progress",
                                **base,
                                "done": event.done,
                                "total": event.total,
                                "message": event.message,
                            }
                        )
                    case EventKind.ENTITY if event.entity is not None:
                        row.count += 1
                        message, spawned = await self._found(session, run, task, row, event)
                        messages.append({**message, **base})
                    case EventKind.COMPLETED | EventKind.FAILED:
                        failed = event.event is EventKind.FAILED
                        row.status = TaskStatus.FAILED if failed else TaskStatus.COMPLETED
                        row.finished_at = now()
                        if event.count is not None:
                            row.count = max(row.count, event.count)
                        if event.error is not None:
                            row.error = event.error.model_dump(mode="json")
                        run.pending.discard(row.id)
                        self._tasks.pop(row.id, None)
                        messages.append(
                            {"type": f"task.{event.event.value}", **base, "task": task_out(row)}
                        )
            for message in messages:
                self.hub.publish(run.investigation_id, message)
            await self._dispatch(run.investigation_id, spawned)
            if not run.pending:
                await self._finish(run)

    async def _found(
        self, session: AsyncSession, run: ActiveRun, task: ActiveTask, row: TaskRow, event: Event
    ) -> tuple[dict[str, Any], list[tuple[Task, TaskRow]]]:
        entity = event.entity
        assert entity is not None
        entity_row, created = await self._upsert_entity(
            session, run.investigation_id, entity, (row.service, row.id)
        )
        run.ids[entity.id] = entity_row.id
        link_out = None
        if event.link is not None:
            source_id = run.ids.get(event.link.from_)
            if source_id is not None and source_id != entity_row.id:
                exists = await session.scalar(
                    select(LinkRow.id).where(
                        LinkRow.source_id == source_id,
                        LinkRow.rel == event.link.rel,
                        LinkRow.target_id == entity_row.id,
                    )
                )
                if exists is None:
                    session.add(
                        LinkRow(
                            investigation_id=run.investigation_id,
                            source_id=source_id,
                            rel=event.link.rel[:32],
                            target_id=entity_row.id,
                        )
                    )
                link_out = {"source": source_id, "rel": event.link.rel, "target": entity_row.id}
        sources = (
            await session.scalars(select(SourceRow).where(SourceRow.entity_id == entity_row.id))
        ).all()
        message = {
            "type": "task.entity" if created else "entity.merged",
            "entity": entity_out(entity_row, list(sources)),
            "link": link_out,
        }
        spawned: list[tuple[Task, TaskRow]] = []
        if task.depth < run.max_depth:
            infos = await self.executor.services()
            for name in await self.plan(entity.type):
                new = self._new_task(
                    session, run, infos, name, entity, entity_row.id, task.depth + 1
                )
                if new is not None:
                    spawned.append(new)
        return message, spawned

    async def _finish(self, run: ActiveRun) -> None:
        self._runs.pop(run.id, None)
        try:
            await self._complete(run)
        finally:
            self._changed()

    async def _complete(self, run: ActiveRun) -> None:
        async with self.sessions.begin() as session:
            groups = await self._correlate(session, run.investigation_id)
            await session.execute(
                update(Run)
                .where(Run.id == run.id)
                .values(status=RunStatus.COMPLETED, finished_at=now())
            )
        self.hub.publish(
            run.investigation_id,
            {
                "type": "run.completed",
                "run_id": run.id,
                "status": RunStatus.COMPLETED,
                "avatar_groups": groups,
            },
        )

    async def _correlate(self, session: AsyncSession, investigation_id: str) -> list[dict]:
        """Recompute avatar groups over the investigation and the scores they change."""
        links = (
            await session.execute(
                select(LinkRow.source_id, LinkRow.rel, LinkRow.target_id).where(
                    LinkRow.investigation_id == investigation_id,
                    LinkRow.rel.in_(("avatar", "hash")),
                )
            )
        ).all()
        hashes = (
            await session.execute(
                select(EntityRow.id, EntityRow.attributes).where(
                    EntityRow.investigation_id == investigation_id,
                    EntityRow.type == EntityType.IMAGE_HASH.value,
                )
            )
        ).all()
        groups = group_avatars(
            [(s, r, t) for s, r, t in links], {entity_id: attrs for entity_id, attrs in hashes}
        )
        group_of = {profile: name for name, profiles, _ in groups for profile in profiles}
        rows = (
            await session.scalars(
                select(EntityRow).where(
                    EntityRow.investigation_id == investigation_id,
                    (EntityRow.avatar_group.is_not(None)) | (EntityRow.id.in_(group_of.keys())),
                )
            )
        ).all()
        for row in rows:
            row.avatar_group = group_of.get(row.id)
            sources = (
                await session.scalars(select(SourceRow).where(SourceRow.entity_id == row.id))
            ).all()
            row.score = score_of(row, list(sources))
        return [
            {"name": name, "profiles": profiles, "phashes": phashes}
            for name, profiles, phashes in groups
        ]
