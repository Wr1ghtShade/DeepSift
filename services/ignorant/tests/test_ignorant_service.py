"""Unit tests: ignorant's site modules are replaced by fakes, nothing leaves the machine."""

from __future__ import annotations

import asyncio

import deepsift_svc_ignorant as svc
from deepsift_sdk import Entity, EntityType, ErrorCode, EventKind, Task, execute


def module(name, seen=None, **result):
    async def probe(phone, country_code, client, out):
        if seen is not None:
            seen.append((phone, country_code))
        if result.get("hang"):
            await asyncio.sleep(60)
        out.append({"name": name, "domain": f"{name}.com", **result})

    probe.__name__ = name
    return probe


async def run_task(monkeypatch, modules, value="+33612345678", **options):
    monkeypatch.setattr(svc, "all_modules", lambda: tuple(modules))
    task = Task(
        service="ignorant",
        input=Entity(type=EntityType.PHONE, value=value),
        options={"module_timeout": 1, **options},
    )
    events = []

    async def sink(event):
        events.append(event)

    final = await execute(svc.IgnorantService(), task, sink)
    return events, final


def test_real_modules_load():
    assert {m.__name__ for m in svc.all_modules()} == {"amazon", "instagram", "snapchat"}


async def test_modules_get_national_number_and_country_code(monkeypatch):
    seen = []
    events, final = await run_task(
        monkeypatch,
        [
            module("instagram", seen, exists=True, rateLimit=False),
            module("snapchat", exists=False, rateLimit=False),
            module("amazon", hang=True),
        ],
    )
    assert seen == [("612345678", "33")]
    assert final.event is EventKind.COMPLETED
    (account,) = [e.entity for e in events if e.event is EventKind.ENTITY]
    assert account.value == "instagram.com:+33612345678"
    messages = [e.message for e in events if e.message]
    assert messages == ["1 sites throttled or unreachable"]


async def test_local_number_with_default_region(monkeypatch):
    seen = []
    _, final = await run_task(
        monkeypatch, [module("x", seen, exists=False)], value="0612345678", default_region="FR"
    )
    assert final.event is EventKind.COMPLETED
    assert seen == [("612345678", "33")]


async def test_invalid_numbers_are_rejected(monkeypatch):
    _, final = await run_task(monkeypatch, [], value="0612345678")
    assert final.error.code is ErrorCode.INVALID_INPUT
    _, final = await run_task(monkeypatch, [], value="+33123")
    assert final.error.code is ErrorCode.INVALID_INPUT
