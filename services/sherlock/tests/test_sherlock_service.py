"""Unit tests: Sherlock's network scan is replaced by a fake, nothing leaves the machine."""

from __future__ import annotations

import deepsift_svc_sherlock as svc
from deepsift_sdk import Entity, EntityType, ErrorCode, EventKind, Task, execute
from sherlock_project.result import QueryResult, QueryStatus


def fake_sherlock(results):
    def run(username, site_data, query_notify, timeout=60):
        for site, url, status in results:
            query_notify.update(QueryResult(username, site, url, status))
        return {}

    return run


async def run_task(monkeypatch, results, username="nightowl_77"):
    monkeypatch.setattr(svc, "sherlock", fake_sherlock(results))
    task = Task(service="sherlock", input=Entity(type=EntityType.USERNAME, value=username))
    events = []

    async def sink(event):
        events.append(event)

    final = await execute(svc.SherlockService(), task, sink)
    return events, final


def test_manifest_is_valid():
    manifest = svc.SherlockService.get_manifest()
    assert manifest.name == "sherlock"
    assert manifest.inputs == [EntityType.USERNAME]
    assert manifest.option_default("site_timeout") == 15


def test_bundled_site_data_loads_without_network():
    data = svc._site_data(False)
    assert len(data) > 100
    assert "GitHub" in data


async def test_claimed_sites_become_profiles(monkeypatch):
    events, final = await run_task(
        monkeypatch,
        [
            ("GitHub", "https://github.com/nightowl_77", QueryStatus.CLAIMED),
            ("Reddit", "https://reddit.com/user/nightowl_77", QueryStatus.AVAILABLE),
            ("Steam", "https://steamcommunity.com/id/nightowl_77", QueryStatus.CLAIMED),
            ("Blocked", "https://blocked.example", QueryStatus.WAF),
        ],
    )
    assert final.event is EventKind.COMPLETED
    assert final.count == 2
    profiles = [e.entity for e in events if e.event is EventKind.ENTITY]
    assert [p.attributes["site"] for p in profiles] == ["GitHub", "Steam"]
    assert profiles[0].value == "https://github.com/nightowl_77"
    assert profiles[0].confidence == svc.CONFIDENCE


async def test_rejects_usernames_with_unsupported_characters(monkeypatch):
    _, final = await run_task(monkeypatch, [], username="a b/c")
    assert final.error.code is ErrorCode.INVALID_INPUT


async def test_sherlock_crash_is_an_upstream_error(monkeypatch):
    def broken(*args, **kwargs):
        raise ConnectionError("network down")

    monkeypatch.setattr(svc, "sherlock", broken)
    task = Task(service="sherlock", input=Entity(type=EntityType.USERNAME, value="x"))

    async def sink(event):
        pass

    final = await execute(svc.SherlockService(), task, sink)
    assert final.error.code is ErrorCode.UPSTREAM_ERROR
    assert final.error.retryable is True


def test_broken_site_definitions_are_fixed():
    discord_bio = svc._site_data(False)["Discord.bio"]
    assert "User not found" in discord_bio["errorMsg"]
    # The fix must not leak into Sherlock's own cached objects between calls.
    assert svc._site_data(False)["Discord.bio"]["errorMsg"].count("User not found") == 1


async def test_excluded_sites_are_not_scanned(monkeypatch):
    seen = {}

    def capture(username, site_data, query_notify, timeout=60):
        seen.update(site_data)
        return {}

    monkeypatch.setattr(svc, "sherlock", capture)
    task = Task(
        service="sherlock",
        input=Entity(type=EntityType.USERNAME, value="nightowl_77"),
        options={"exclude_sites": "discord.bio, GitHub"},
    )

    async def sink(event):
        pass

    await execute(svc.SherlockService(), task, sink)
    assert seen and "Discord.bio" not in seen and "GitHub" not in seen
    assert "GitLab" in seen
