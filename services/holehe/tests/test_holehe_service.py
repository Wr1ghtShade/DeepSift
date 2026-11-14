"""Unit tests: holehe's site modules are replaced by fakes, nothing leaves the machine."""

from __future__ import annotations

import asyncio

import deepsift_svc_holehe as svc
from deepsift_sdk import Entity, EntityType, ErrorCode, EventKind, Task, execute


def module(name, **result):
    async def probe(email, client, out):
        if result.get("hang"):
            await asyncio.sleep(60)
        if result.get("crash"):
            raise RuntimeError("site changed")
        out.append({"name": name, "domain": f"{name}.com", "method": "register", **result})

    probe.__name__ = name
    return probe


async def run_task(monkeypatch, modules, email="night.owl@example.org", **options):
    monkeypatch.setattr(svc, "all_modules", lambda: tuple(modules))
    task = Task(
        service="holehe",
        input=Entity(type=EntityType.EMAIL, value=email),
        options={"module_timeout": 1, **options},
    )
    events = []

    async def sink(event):
        events.append(event)

    final = await execute(svc.HoleheService(), task, sink)
    return events, final


def found(events):
    return [e.entity for e in events if e.event is EventKind.ENTITY]


def test_manifest_and_real_modules_load():
    assert svc.HoleheService.get_manifest().inputs == [EntityType.EMAIL]
    names = {m.__name__ for m in svc.all_modules()}
    assert {"github", "instagram"} <= names
    default = {m.__name__ for m in svc.select_modules(False, False)}
    assert not default & (svc.PASSWORD_RECOVERY | svc.NSFW)


async def test_registered_sites_become_accounts(monkeypatch):
    events, final = await run_task(
        monkeypatch,
        [
            module("github", exists=True, rateLimit=False, emailrecovery="n*****@e*****.org"),
            module("spotify", exists=False, rateLimit=False),
            module("twitter", exists=False, rateLimit=True),
        ],
    )
    assert final.event is EventKind.COMPLETED
    (account,) = found(events)
    assert account.type is EntityType.ACCOUNT
    assert account.value == "github.com:night.owl@example.org"
    assert account.attributes["recovery_email"] == "n*****@e*****.org"
    link = next(e.link for e in events if e.event is EventKind.ENTITY)
    assert link.rel == "registered_on"
    messages = [e.message for e in events if e.event is EventKind.PROGRESS and e.message]
    assert messages == ["1 sites throttled or unreachable"]


async def test_broken_and_slow_modules_do_not_fail_the_task(monkeypatch):
    events, final = await run_task(
        monkeypatch,
        [module("slow", hang=True), module("broken", crash=True), module("ok", exists=True)],
    )
    assert final.event is EventKind.COMPLETED
    assert [a.attributes["site"] for a in found(events)] == ["ok.com"]


async def test_password_recovery_modules_are_opt_in(monkeypatch):
    modules = [module("adobe", exists=True), module("github", exists=True)]
    events, _ = await run_task(monkeypatch, modules)
    assert [a.attributes["site"] for a in found(events)] == ["github.com"]
    events, _ = await run_task(monkeypatch, modules, password_recovery=True)
    assert sorted(a.attributes["site"] for a in found(events)) == ["adobe.com", "github.com"]


async def test_rejects_non_email(monkeypatch):
    task = Task(service="holehe", input=Entity(type=EntityType.EMAIL, value="nope"))

    async def sink(event):
        pass

    final = await execute(svc.HoleheService(), task, sink)
    assert final.error.code is ErrorCode.INVALID_INPUT
