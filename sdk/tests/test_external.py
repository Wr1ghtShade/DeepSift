"""ExternalService runs a child process: these tests use small Python scripts as children."""

from __future__ import annotations

import sys
import textwrap

import pytest
from deepsift_sdk import Entity, EntityType, ErrorCode, EventKind, Task, execute
from deepsift_sdk.external import ExternalService
from deepsift_sdk.local import LocalRun
from fakes import FakeService, make_manifest

CHILD_OK = """
import json, sys
task = json.loads(sys.stdin.readline())
def out(**event):
    print(json.dumps({"contract": 1, "task_id": "child", "service": "child", **event}), flush=True)
print("debug noise", file=sys.stderr)
out(event="started")
out(event="progress", done=1, total=2)
profile = {"id": "ent_p", "type": "profile", "value": "https://wa.me/" + task["input"]["value"][1:]}
out(event="entity", entity=profile, link={"from": task["input"]["id"], "rel": "found_on"})
image = {"id": "ent_i", "type": "image", "value": "https://cdn.example/p.jpg"}
out(event="entity", entity=image, link={"from": "ent_p", "rel": "avatar"})
print("not json", flush=True)
out(event="completed", count=2)
"""

CHILD_FAIL = """
import json, sys
sys.stdin.readline()
print(json.dumps({"contract": 1, "task_id": "c", "service": "c", "event": "failed",
                  "error": {"code": "rate_limited", "message": "daily cap", "retryable": False}}))
"""

CHILD_CRASH = """
import sys
sys.stdin.readline()
print("Traceback: boom", file=sys.stderr)
sys.exit(3)
"""


def external(script: str, tmp_path, name="ext"):
    path = tmp_path / f"{name}.py"
    path.write_text(textwrap.dedent(script))

    class Child(ExternalService):
        _manifest = make_manifest(name, inputs=["phone"], outputs=["profile", "image"])
        command = (sys.executable, str(path))

        @classmethod
        def get_manifest(cls):
            return cls._manifest

    return Child()


async def run(service):
    task = Task(
        service=service.manifest.name, input=Entity(type=EntityType.PHONE, value="+33612345678")
    )
    events = []

    async def sink(event):
        events.append(event)

    final = await execute(service, task, sink)
    return task, events, final


async def test_child_events_are_relayed(tmp_path):
    task, events, final = await run(external(CHILD_OK, tmp_path))
    assert final.event is EventKind.COMPLETED
    assert final.count == 2
    kinds = [e.event for e in events]
    assert kinds == [
        EventKind.STARTED,
        EventKind.PROGRESS,
        EventKind.ENTITY,
        EventKind.ENTITY,
        EventKind.COMPLETED,
    ]
    assert all(e.task_id == task.task_id and e.service == "ext" for e in events)
    profile, image = (e for e in events if e.event is EventKind.ENTITY)
    assert profile.link.from_ == task.input.id
    assert (image.link.from_, image.link.rel) == ("ent_p", "avatar")


async def test_child_failure_keeps_its_error(tmp_path):
    _, _, final = await run(external(CHILD_FAIL, tmp_path))
    assert final.error.code is ErrorCode.RATE_LIMITED
    assert final.error.retryable is False
    assert final.error.message == "daily cap"


async def test_child_crash_is_internal_with_stderr(tmp_path):
    _, _, final = await run(external(CHILD_CRASH, tmp_path))
    assert final.error.code is ErrorCode.INTERNAL
    assert "Traceback: boom" in final.error.message


async def test_missing_program_needs_config(tmp_path):
    class Missing(ExternalService):
        _manifest = make_manifest("missing", inputs=["phone"])
        command = ("deepsift-no-such-program",)
        install_hint = "npm install -g something"

        @classmethod
        def get_manifest(cls):
            return cls._manifest

    _, _, final = await run(Missing())
    assert final.error.code is ErrorCode.NEEDS_CONFIG
    assert "npm install -g something" in final.error.message


async def test_command_override_from_environment(tmp_path, monkeypatch):
    service = external(CHILD_FAIL, tmp_path, name="over-ride")
    ok = tmp_path / "ok.py"
    ok.write_text(textwrap.dedent(CHILD_OK))
    monkeypatch.setenv("DEEPSIFT_OVER_RIDE_CMD", f"{sys.executable} {ok}")
    _, _, final = await run(service)
    assert final.event is EventKind.COMPLETED


async def test_opt_in_services_run_only_when_enabled():
    class OptIn(FakeService):
        _manifest = make_manifest("opt-in", enabled_by_default=False)

    services = {"fake": FakeService(), "opt-in": OptIn()}
    events = [e async for e in LocalRun(services).run("alice")]
    assert {e.service for e in events} == {"fake"}
    events = [e async for e in LocalRun(services, enabled={"opt-in"}).run("alice")]
    assert {e.service for e in events} == {"fake", "opt-in"}
    events = [e async for e in LocalRun(services).run("alice", only=["opt-in"])]
    assert {e.service for e in events} == {"opt-in"}
    with pytest.raises(ValueError):
        LocalRun(services, enabled={"ghost"})


async def test_concurrency_is_honoured():
    import asyncio

    running = 0
    peak = 0

    class Single(FakeService):
        _manifest = make_manifest("single", inputs=["image"], concurrency=1)

        async def run(self, task, ctx):
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.02)
            running -= 1

    from fakes import AvatarProfileService

    run_ = LocalRun({"avatar-profiles": AvatarProfileService(), "single": Single()})
    [e async for e in run_.run("alice")]
    assert peak == 1
