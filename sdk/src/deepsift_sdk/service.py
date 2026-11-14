"""The base class every DeepSift service inherits."""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, ClassVar

from .entities import Entity, Link
from .manifest import Manifest, load_manifest
from .messages import ErrorCode, ErrorInfo, Event, EventKind, Task

EventSink = Callable[[Event], Awaitable[None]]


class ServiceError(Exception):
    """Raise from Service.run to fail a task with a contract error code."""

    def __init__(self, code: ErrorCode, message: str, retryable: bool | None = None) -> None:
        super().__init__(message)
        self.info = ErrorInfo.of(code, message, retryable)


class TaskContext:
    """What a service uses to report progress and findings for one task."""

    def __init__(self, task: Task, manifest: Manifest, sink: EventSink) -> None:
        self.task = task
        self.manifest = manifest
        self._sink = sink
        self.count = 0

    def option(self, name: str) -> Any:
        """The task's value for an option, or the manifest default."""
        if name in self.task.options:
            return self.task.options[name]
        return self.manifest.option_default(name)

    async def found(
        self, entity: Entity, rel: str = "found_on", parent: Entity | None = None
    ) -> None:
        """Report one finding.

        It is linked from the task's input entity, or from ``parent``: an entity this
        task reported earlier (for example a profile, for the avatar found on it).
        """
        self.count += 1
        await self._sink(
            Event(
                task_id=self.task.task_id,
                service=self.manifest.name,
                event=EventKind.ENTITY,
                entity=entity,
                link=Link(from_=(parent or self.task.input).id, rel=rel),
            )
        )

    async def progress(self, done: int, total: int, message: str | None = None) -> None:
        await self._sink(
            Event(
                task_id=self.task.task_id,
                service=self.manifest.name,
                event=EventKind.PROGRESS,
                done=done,
                total=total,
                message=message,
            )
        )


class Service(ABC):
    """Subclass this, put a manifest.yaml next to the module, and implement run()."""

    manifest_file: ClassVar[str] = "manifest.yaml"
    _manifest: ClassVar[Manifest | None] = None

    @classmethod
    def get_manifest(cls) -> Manifest:
        if cls.__dict__.get("_manifest") is None:
            path = Path(inspect.getfile(cls)).parent / cls.manifest_file
            cls._manifest = load_manifest(path)
        return cls._manifest  # type: ignore[return-value]

    @property
    def manifest(self) -> Manifest:
        return self.get_manifest()

    async def setup(self) -> None:  # noqa: B027 - optional hook
        """Called once before the first task. Load data, open clients."""

    async def close(self) -> None:  # noqa: B027 - optional hook
        """Called once on shutdown."""

    @abstractmethod
    async def run(self, task: Task, ctx: TaskContext) -> None:
        """Process one task. Report findings with ctx.found() as they come."""
