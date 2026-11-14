"""Services written in another language, run as a child process (contract section 9).

The child reads one task as a JSON line on stdin and writes contract events as JSON
lines on stdout, ending with ``completed`` or ``failed``. Anything on stderr is logs.
In the stack, the same program talks to Redis directly; this bridge is for local mode.

A Python package declares the service with a thin subclass::

    class WhatsAppService(ExternalService):
        command = ("deepsift-whatsapp", "stdio")
        install_hint = "npm install -g ./services/whatsapp"
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shlex
import shutil
from collections import deque
from typing import ClassVar

from pydantic import ValidationError

from .messages import ErrorCode, Event, EventKind, Task
from .service import Service, ServiceError, TaskContext

log = logging.getLogger(__name__)

#: Longest line accepted from a child, in bytes.
LINE_LIMIT = 1 << 20


class ExternalService(Service):
    #: Program and arguments. Overridden by ``DEEPSIFT_<NAME>_CMD`` (shell syntax).
    command: ClassVar[tuple[str, ...]] = ()
    #: Shown when the program cannot be found.
    install_hint: ClassVar[str] = ""

    @classmethod
    def resolve_command(cls) -> list[str]:
        name = cls.get_manifest().name.upper().replace("-", "_")
        override = os.environ.get(f"DEEPSIFT_{name}_CMD")
        argv = shlex.split(override) if override else list(cls.command)
        if not argv or shutil.which(argv[0]) is None:
            hint = f" Install it: {cls.install_hint}" if cls.install_hint else ""
            raise ServiceError(
                ErrorCode.NEEDS_CONFIG,
                f"program not found: {argv[0] if argv else '(none)'}.{hint}",
            )
        return argv

    async def run(self, task: Task, ctx: TaskContext) -> None:
        argv = self.resolve_command()
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=LINE_LIMIT,
        )
        stderr_tail: deque[str] = deque(maxlen=20)

        async def drain_stderr() -> None:
            assert process.stderr is not None
            async for raw in process.stderr:
                line = raw.decode(errors="replace").rstrip()
                stderr_tail.append(line)
                log.debug("%s: %s", argv[0], line)

        stderr_job = asyncio.create_task(drain_stderr())
        final: Event | None = None
        try:
            assert process.stdin is not None and process.stdout is not None
            process.stdin.write(task.model_dump_json(by_alias=True).encode() + b"\n")
            await process.stdin.drain()
            process.stdin.close()
            async for raw in process.stdout:
                line = raw.strip()
                if not line:
                    continue
                try:
                    event = Event.model_validate_json(line)
                except ValidationError:
                    log.warning("%s wrote a line that is not an event", argv[0])
                    continue
                if event.is_final:
                    final = event
                    break
                await ctx.relay(event)
            await process.wait()
        finally:
            if process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
                await process.wait()
            stderr_job.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await stderr_job

        if final is None:
            detail = stderr_tail[-1] if stderr_tail else f"exit code {process.returncode}"
            raise ServiceError(ErrorCode.INTERNAL, f"{argv[0]} stopped without a result: {detail}")
        if final.event is EventKind.FAILED and final.error is not None:
            raise ServiceError(final.error.code, final.error.message, final.error.retryable)
