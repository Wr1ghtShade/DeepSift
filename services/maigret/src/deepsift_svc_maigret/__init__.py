"""DeepSift service wrapping Maigret (https://github.com/soxoj/maigret, MIT).

Maigret is asynchronous (aiohttp), so it runs directly in the event loop. Its notifier
is called as each site finishes; results are queued and turned into entities while the
scan goes on:

- ``profile`` for every account found (``found_on`` the username)
- ``image`` for the avatar extracted from a profile (``avatar`` from the profile)
- ``identity`` for the display name extracted from a profile (``identity`` from it)
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
from functools import cache
from typing import Any

from deepsift_sdk import Entity, EntityType, ErrorCode, Service, ServiceError, Task, TaskContext
from maigret.checking import maigret
from maigret.db_updater import BUNDLED_DB_PATH
from maigret.result import MaigretCheckResult, MaigretCheckStatus
from maigret.sites import MaigretDatabase, MaigretSite

__all__ = ["MaigretService"]

#: Maigret checks more signals than Sherlock and confirms many accounts by parsing them.
CONFIDENCE = 0.7
CONFIDENCE_PARSED = 0.8
IDENTITY_CONFIDENCE = 0.5
PROGRESS_EVERY = 25
_VALID_USERNAME = re.compile(r"^[^\s/?#{}]{1,64}$")

#: socid-extractor field names mapped to DeepSift profile attributes, first match wins.
_FIELDS = {
    "display_name": ("fullname", "name", "full_name", "nickname"),
    "bio": ("bio", "description", "about"),
    "location": ("location", "country", "city"),
    "created_at": ("created_at", "registered_at", "joined"),
    "avatar_url": ("image", "avatar", "picture"),
}

log = logging.getLogger("deepsift.maigret")
_maigret_log = logging.getLogger("maigret")
_maigret_log.setLevel(logging.ERROR)


@cache
def _database() -> MaigretDatabase:
    """Site definitions bundled with the installed Maigret release (no network)."""
    return MaigretDatabase().load_from_path(BUNDLED_DB_PATH)


def _sites(top: int) -> dict[str, MaigretSite]:
    return _database().ranked_sites_dict(
        top=top if top > 0 else sys.maxsize, disabled=False, id_type="username"
    )


def profile_attributes(result: MaigretCheckResult, username: str) -> dict[str, Any]:
    """Turn Maigret's extracted ids_data into DeepSift profile attributes."""
    ids = dict(result.ids_data or {})
    attributes: dict[str, Any] = {"site": result.site_name, "username": username}
    for target, sources in _FIELDS.items():
        for key in sources:
            value = ids.pop(key, None)
            if value not in (None, "", [], {}):
                attributes.setdefault(target, value)
    links = ids.pop("links", None)
    if links:
        attributes["links"] = links if isinstance(links, list) else [links]
    extra = {k: v for k, v in ids.items() if isinstance(v, str | int | float | bool)}
    if extra:
        attributes["extra"] = extra
    tags = list(getattr(result, "tags", None) or [])
    if tags:
        attributes["tags"] = tags
    return attributes


class _Relay:
    """Maigret notifier: queues each site result for the task loop."""

    def __init__(self, queue: asyncio.Queue[MaigretCheckResult]) -> None:
        self._queue = queue

    def start(self, message: Any = None, id_type: str = "username") -> None:
        pass

    def update(self, result: MaigretCheckResult, is_similar: bool = False) -> None:
        if not is_similar:
            self._queue.put_nowait(result)

    def finish(self, message: Any = None) -> None:
        pass

    def warning(self, *args: Any, **kwargs: Any) -> None:
        pass


class MaigretService(Service):
    async def setup(self) -> None:
        await asyncio.to_thread(_database)

    async def run(self, task: Task, ctx: TaskContext) -> None:
        username = task.input.value
        if not _VALID_USERNAME.match(username):
            raise ServiceError(ErrorCode.INVALID_INPUT, "username has unsupported characters")

        sites = await asyncio.to_thread(_sites, int(ctx.option("top_sites")))
        total = len(sites)
        queue: asyncio.Queue[MaigretCheckResult] = asyncio.Queue()
        scan = asyncio.ensure_future(
            maigret(
                username=username,
                site_dict=sites,
                logger=_maigret_log,
                query_notify=_Relay(queue),
                timeout=int(ctx.option("site_timeout")),
                is_parsing_enabled=bool(ctx.option("parse_profiles")),
                max_connections=int(ctx.option("max_connections")),
                no_progressbar=True,
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
                if result.status == MaigretCheckStatus.CLAIMED:
                    await self._report(ctx, result, username)
                if done % PROGRESS_EVERY == 0 or done == total:
                    await ctx.progress(done, total)
            await scan  # re-raise any error from Maigret itself
            # Maigret does not notify every site (some fail silently): close the lane.
            await ctx.progress(total, total)
        except ServiceError:
            raise
        except Exception as exc:
            raise ServiceError(ErrorCode.UPSTREAM_ERROR, f"maigret failed: {exc}") from exc
        finally:
            if not scan.done():
                scan.cancel()

    async def _report(self, ctx: TaskContext, result: MaigretCheckResult, username: str) -> None:
        attributes = profile_attributes(result, username)
        parsed = any(key in attributes for key in _FIELDS)
        profile = Entity(
            type=EntityType.PROFILE,
            value=result.site_url_user,
            attributes=attributes,
            confidence=CONFIDENCE_PARSED if parsed else CONFIDENCE,
        )
        await ctx.found(profile)

        avatar = attributes.get("avatar_url")
        if isinstance(avatar, str) and avatar.startswith(("http://", "https://")):
            await ctx.found(
                Entity(
                    type=EntityType.IMAGE,
                    value=avatar,
                    attributes={"site": result.site_name, "role": "avatar"},
                    confidence=profile.confidence,
                ),
                rel="avatar",
                parent=profile,
            )

        name = attributes.get("display_name")
        if isinstance(name, str) and name.strip() and name.strip() != username:
            await ctx.found(
                Entity(
                    type=EntityType.IDENTITY,
                    value=name.strip(),
                    attributes={"name": name.strip(), "site": result.site_name},
                    confidence=IDENTITY_CONFIDENCE,
                ),
                rel="identity",
                parent=profile,
            )
