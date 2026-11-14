"""DeepSift service wrapping ignorant (https://github.com/megadose/ignorant, GPL-3.0).

Each ignorant module is an async function ``module(national_number, country_code,
client, out)`` probing one site, and appending a result dict to ``out``. Every site where
the number is used becomes an ``account`` entity (rel ``registered_on``).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from functools import cache
from typing import Any

import httpx
import phonenumbers
from deepsift_sdk import Entity, EntityType, ErrorCode, Service, ServiceError, Task, TaskContext
from ignorant.core import get_functions, import_submodules

__all__ = ["IgnorantService"]

Module = Callable[[str, str, httpx.AsyncClient, list[dict[str, Any]]], Awaitable[None]]

CONFIDENCE = 0.7


@cache
def all_modules() -> tuple[Module, ...]:
    return tuple(get_functions(import_submodules("ignorant.modules")))


def split_number(value: str, default_region: str) -> tuple[str, str, str]:
    """(country code, national number, E.164) of a number."""
    region = default_region.upper() or None
    if not value.startswith("+") and region is None:
        raise ServiceError(
            ErrorCode.INVALID_INPUT,
            "number has no country code: write it as +33… or set the default_region option",
        )
    try:
        number = phonenumbers.parse(value, region)
    except phonenumbers.NumberParseException as exc:
        raise ServiceError(ErrorCode.INVALID_INPUT, f"not a phone number: {exc}") from exc
    if not phonenumbers.is_valid_number(number):
        raise ServiceError(ErrorCode.INVALID_INPUT, "not a valid phone number")
    e164 = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
    return str(number.country_code), str(number.national_number), e164


class IgnorantService(Service):
    async def setup(self) -> None:
        await asyncio.to_thread(all_modules)

    async def run(self, task: Task, ctx: TaskContext) -> None:
        country_code, national, e164 = split_number(
            task.input.value, str(ctx.option("default_region") or "")
        )
        modules = all_modules()
        timeout = float(ctx.option("module_timeout"))
        throttled = 0

        async def probe(module: Module, client: httpx.AsyncClient) -> list[dict[str, Any]]:
            out: list[dict[str, Any]] = []
            try:
                await asyncio.wait_for(module(national, country_code, client, out), timeout)
            except Exception:  # noqa: BLE001 - a broken site module is a skipped site
                out.append({"name": module.__name__, "rateLimit": True, "exists": False})
            return out

        async with httpx.AsyncClient(timeout=timeout) as client:
            results = await asyncio.gather(*(probe(m, client) for m in modules))

        for done, out in enumerate(results, start=1):
            for result in out:
                if result.get("rateLimit"):
                    throttled += 1
                elif result.get("exists"):
                    domain = str(result.get("domain") or result.get("name"))
                    await ctx.found(
                        Entity(
                            type=EntityType.ACCOUNT,
                            value=f"{domain}:{e164}",
                            attributes={"site": domain, "phone": e164},
                            confidence=CONFIDENCE,
                        ),
                        rel="registered_on",
                    )
            await ctx.progress(done, len(results))
        if throttled:
            await ctx.progress(
                len(results), len(results), f"{throttled} sites throttled or unreachable"
            )
