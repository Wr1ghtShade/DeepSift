"""DeepSift service wrapping Sherlock (https://github.com/sherlock-project/sherlock, MIT).

Sherlock is synchronous (requests + a thread pool), so it runs in a worker thread.
Each site result is pushed back to the event loop as it arrives, so findings and
progress stream out while the scan is still running.
"""

from __future__ import annotations

import asyncio
import re
from functools import cache
from importlib.resources import files
from typing import Any

from deepsift_sdk import Entity, EntityType, ErrorCode, Service, ServiceError, Task, TaskContext
from sherlock_project.notify import QueryNotify
from sherlock_project.result import QueryResult, QueryStatus
from sherlock_project.sherlock import sherlock
from sherlock_project.sites import SitesInformation

__all__ = ["SherlockService"]

#: Sherlock reports false positives on some sites, so a single hit is "medium".
CONFIDENCE = 0.6
PROGRESS_EVERY = 25
_VALID_USERNAME = re.compile(r"^[^\s/?#{}]{1,64}$")


@cache
def _site_data(include_nsfw: bool) -> dict[str, dict[str, Any]]:
    """Site definitions bundled with the installed Sherlock release.

    The bundled file keeps scans reproducible and avoids a network call at startup.
    """
    data_file = files("sherlock_project") / "resources" / "data.json"
    sites = SitesInformation(data_file_path=str(data_file), honor_exclusions=False)
    if not include_nsfw:
        sites.remove_nsfw_sites()
    return {site.name: site.information for site in sites}


class _Relay(QueryNotify):
    """Forwards each site result from Sherlock's thread to the event loop."""

    def __init__(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue) -> None:
        super().__init__()
        self._loop = loop
        self._queue = queue

    def start(self, message: Any = None) -> None:
        pass

    def update(self, result: QueryResult) -> None:
        self._loop.call_soon_threadsafe(self._queue.put_nowait, result)

    def finish(self, message: Any = None) -> None:
        pass


class SherlockService(Service):
    async def setup(self) -> None:
        await asyncio.to_thread(_site_data, False)

    async def run(self, task: Task, ctx: TaskContext) -> None:
        username = task.input.value
        if not _VALID_USERNAME.match(username):
            raise ServiceError(ErrorCode.INVALID_INPUT, "username has unsupported characters")

        site_data = await asyncio.to_thread(_site_data, bool(ctx.option("include_nsfw")))
        total = len(site_data)
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[QueryResult] = asyncio.Queue()
        scan = asyncio.ensure_future(
            asyncio.to_thread(
                sherlock,
                username,
                site_data,
                _Relay(loop, queue),
                timeout=int(ctx.option("site_timeout")),
            )
        )

        done = 0
        try:
            while not (scan.done() and queue.empty()):
                try:
                    result = await asyncio.wait_for(queue.get(), timeout=0.5)
                except TimeoutError:
                    continue
                done += 1
                if result.status == QueryStatus.CLAIMED:
                    await ctx.found(
                        Entity(
                            type=EntityType.PROFILE,
                            value=result.site_url_user,
                            attributes={"site": result.site_name, "username": username},
                            confidence=CONFIDENCE,
                        )
                    )
                if done % PROGRESS_EVERY == 0 or done == total:
                    await ctx.progress(done, total)
            await scan  # re-raise any error from Sherlock itself
        except Exception as exc:
            if isinstance(exc, ServiceError):
                raise
            raise ServiceError(ErrorCode.UPSTREAM_ERROR, f"sherlock failed: {exc}") from exc
        finally:
            if not scan.done():
                scan.cancel()
