from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from deepsift_sdk import Entity, EntityType, ErrorCode, EventKind, Task, execute
from deepsift_sdk.local import LocalRun
from fakes import FakeService, OtherFakeService


async def collect(service, task):
    events = []

    async def sink(event):
        events.append(event)

    final = await execute(service, task, sink)
    return events, final


async def test_success_sends_started_findings_and_completed(username_task):
    events, final = await collect(FakeService(), username_task)
    kinds = [e.event for e in events]
    assert kinds == [EventKind.STARTED, EventKind.PROGRESS, EventKind.ENTITY, EventKind.COMPLETED]
    assert final.count == 1
    found = events[2]
    assert found.link.from_ == username_task.input.id
    assert found.link.rel == "found_on"


@pytest.mark.parametrize(
    ("behaviour", "code", "retryable"),
    [
        ("raise", ErrorCode.INTERNAL, False),
        ("service_error", ErrorCode.RATE_LIMITED, True),
    ],
)
async def test_failures_become_contract_errors(username_task, behaviour, code, retryable):
    username_task.options["behaviour"] = behaviour
    _, final = await collect(FakeService(), username_task)
    assert final.event is EventKind.FAILED
    assert final.error.code is code
    assert final.error.retryable is retryable


async def test_internal_error_message_does_not_leak_details(username_task):
    username_task.options["behaviour"] = "raise"
    _, final = await collect(FakeService(), username_task)
    assert "boom" not in final.error.message


async def test_deadline_turns_into_timeout(username_task):
    username_task.options["behaviour"] = "sleep"
    username_task.deadline = datetime.now(UTC) + timedelta(milliseconds=50)
    _, final = await collect(FakeService(), username_task)
    assert final.error.code is ErrorCode.TIMEOUT


async def test_wrong_input_type_is_rejected():
    task = Task(service="fake", input=Entity(type=EntityType.EMAIL, value="a@b.org"))
    _, final = await collect(FakeService(), task)
    assert final.error.code is ErrorCode.INVALID_INPUT


async def test_missing_secret_is_needs_config(username_task, monkeypatch):
    from fakes import make_manifest

    class KeyedService(FakeService):
        _manifest = make_manifest("keyed", secrets=["DEEPSIFT_TEST_KEY"])

    monkeypatch.delenv("DEEPSIFT_TEST_KEY", raising=False)
    _, final = await collect(KeyedService(), username_task)
    assert final.error.code is ErrorCode.NEEDS_CONFIG
    monkeypatch.setenv("DEEPSIFT_TEST_KEY", "x")
    _, final = await collect(KeyedService(), username_task)
    assert final.event is EventKind.COMPLETED


async def test_local_run_merges_findings_with_noisy_or():
    run = LocalRun({"fake": FakeService(), "other-fake": OtherFakeService()})
    events = [event async for event in run.run("alice")]
    assert sum(e.event is EventKind.COMPLETED for e in events) == 2
    assert run.input.type is EntityType.USERNAME
    best, other = run.findings
    assert best.entity.value == "https://example.org/u/alice"
    assert best.sources == {"fake": 0.6, "other-fake": 0.7}
    assert best.score == 0.88
    assert best.level == "high"
    assert other.score == 0.4


async def test_local_run_skips_services_that_do_not_accept_the_type():
    run = LocalRun({"fake": FakeService()})
    events = [event async for event in run.run("a@b.org")]
    assert events == []
    assert run.input.type is EntityType.EMAIL


def test_local_run_rejects_unknown_services():
    run = LocalRun({"fake": FakeService()})
    with pytest.raises(ValueError, match="nope"):
        run.plan(EntityType.USERNAME, ["nope"])
