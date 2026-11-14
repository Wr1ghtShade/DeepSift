"""DeepSift service wrapping holehe (https://github.com/megadose/holehe, GPL-3.0).

Each holehe module is an async function ``module(email, client, out)`` that probes one
site and appends a result dict to ``out``. They run in parallel on a shared httpx client;
every site where the address is registered becomes an ``account`` entity.

Modules that go through a password-recovery form are off by default: the target could
notice them. Adult sites are off by default too.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from functools import cache
from typing import Any

import httpx
from deepsift_sdk import Entity, EntityType, ErrorCode, Service, ServiceError, Task, TaskContext
from holehe.core import get_functions, import_submodules

__all__ = ["HoleheService"]

Module = Callable[[str, httpx.AsyncClient, list[dict[str, Any]]], Awaitable[None]]

CONFIDENCE = 0.7
#: Modules holehe itself skips with --no-password-recovery.
PASSWORD_RECOVERY = frozenset({"adobe", "mail_ru", "odnoklassniki", "samsung"})
NSFW = frozenset({"pornhub", "redtube", "xnxx", "xvideos", "babeshows"})


@cache
def all_modules() -> tuple[Module, ...]:
    return tuple(get_functions(import_submodules("holehe.modules")))


def select_modules(password_recovery: bool, include_nsfw: bool) -> list[Module]:
    skip = set()
    if not password_recovery:
        skip |= PASSWORD_RECOVERY
    if not include_nsfw:
        skip |= NSFW
    return [module for module in all_modules() if module.__name__ not in skip]


def account_entity(email: str, result: dict[str, Any]) -> Entity:
    domain = str(result.get("domain") or result.get("name"))
    attributes: dict[str, Any] = {"site": domain, "email": email, "method": result.get("method")}
    if result.get("emailrecovery"):
        attributes["recovery_email"] = result["emailrecovery"]
    if result.get("phoneNumber"):
        attributes["recovery_phone"] = result["phoneNumber"]
    if isinstance(result.get("others"), dict):
        attributes["extra"] = {k: v for k, v in result["others"].items() if v not in (None, "")}
    return Entity(
        type=EntityType.ACCOUNT,
        value=f"{domain}:{email}",
        attributes={k: v for k, v in attributes.items() if v is not None},
        confidence=CONFIDENCE,
    )


class HoleheService(Service):
    async def setup(self) -> None:
        await asyncio.to_thread(all_modules)

    async def run(self, task: Task, ctx: TaskContext) -> None:
        email = task.input.value
        if "@" not in email:
            raise ServiceError(ErrorCode.INVALID_INPUT, "not an email address")

        modules = select_modules(
            bool(ctx.option("password_recovery")), bool(ctx.option("include_nsfw"))
        )
        total = len(modules)
        slots = asyncio.Semaphore(int(ctx.option("parallel")))
        timeout = float(ctx.option("module_timeout"))
        done = 0
        rate_limited = 0

        async def probe(module: Module, client: httpx.AsyncClient) -> list[dict[str, Any]]:
            out: list[dict[str, Any]] = []
            async with slots:
                try:
                    await asyncio.wait_for(module(email, client, out), timeout)
                except Exception:  # noqa: BLE001 - a broken site module is a skipped site
                    out.append({"name": module.__name__, "rateLimit": True, "exists": False})
            return out

        async with httpx.AsyncClient(timeout=timeout) as client:
            jobs = [asyncio.create_task(probe(module, client)) for module in modules]
            try:
                for finished in asyncio.as_completed(jobs):
                    for result in await finished:
                        if result.get("rateLimit"):
                            rate_limited += 1
                        elif result.get("exists"):
                            await ctx.found(account_entity(email, result), rel="registered_on")
                    done += 1
                    if done % 10 == 0 or done == total:
                        await ctx.progress(done, total)
            finally:
                for job in jobs:
                    job.cancel()
        if rate_limited:
            await ctx.progress(total, total, f"{rate_limited} sites throttled or unreachable")
