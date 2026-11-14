"""Run one task through a service and turn the outcome into contract events."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from .messages import ErrorCode, ErrorInfo, Event, EventKind, Task
from .service import EventSink, Service, ServiceError, TaskContext

log = logging.getLogger(__name__)


def _time_left(task: Task, default: float) -> float:
    if task.deadline is None:
        return default
    left = (task.deadline - datetime.now(UTC)).total_seconds()
    return max(0.0, min(default, left))


async def execute(service: Service, task: Task, sink: EventSink) -> Event:
    """Run the task, send started/entity/progress events, and return the final event.

    The final event (completed or failed) is also sent to the sink.
    """
    manifest = service.manifest
    await sink(Event(task_id=task.task_id, service=manifest.name, event=EventKind.STARTED))

    async def finish(error: ErrorInfo | None, count: int = 0) -> Event:
        if error is None:
            final = Event(
                task_id=task.task_id,
                service=manifest.name,
                event=EventKind.COMPLETED,
                count=count,
            )
        else:
            final = Event(
                task_id=task.task_id, service=manifest.name, event=EventKind.FAILED, error=error
            )
        await sink(final)
        return final

    if not manifest.accepts(task.input.type):
        return await finish(
            ErrorInfo.of(
                ErrorCode.INVALID_INPUT,
                f"{manifest.name} does not accept {task.input.type.value}",
            )
        )
    missing = manifest.missing_secrets()
    if missing:
        return await finish(
            ErrorInfo.of(ErrorCode.NEEDS_CONFIG, f"missing secrets: {', '.join(missing)}")
        )

    ctx = TaskContext(task, manifest, sink)
    timeout = _time_left(task, manifest.timeout)
    try:
        await asyncio.wait_for(service.run(task, ctx), timeout=timeout)
    except TimeoutError:
        return await finish(
            ErrorInfo.of(ErrorCode.TIMEOUT, f"no result within {timeout:.0f}s"), ctx.count
        )
    except ServiceError as exc:
        return await finish(exc.info, ctx.count)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - any bug in a service becomes a failed task
        log.exception("service %s failed on task %s", manifest.name, task.task_id)
        return await finish(
            ErrorInfo.of(ErrorCode.INTERNAL, f"unexpected {type(exc).__name__}"), ctx.count
        )
    return await finish(None, ctx.count)
