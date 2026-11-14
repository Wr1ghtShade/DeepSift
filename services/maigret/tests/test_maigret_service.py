"""Unit tests: Maigret's network scan is replaced by a fake, nothing leaves the machine."""

from __future__ import annotations

import deepsift_svc_maigret as svc
from deepsift_sdk import Entity, EntityType, ErrorCode, EventKind, Task, execute
from maigret.result import MaigretCheckResult, MaigretCheckStatus


def claimed(site, url, ids_data=None):
    return MaigretCheckResult(
        "nightowl_77", site, url, MaigretCheckStatus.CLAIMED, ids_data=ids_data
    )


def fake_maigret(results, similar=()):
    async def run(username, site_dict, logger, query_notify=None, **kwargs):
        query_notify.start(username, "username")
        for result in similar:
            query_notify.update(result, True)
        for result in results:
            query_notify.update(result)
        query_notify.finish()
        return {}

    return run


async def run_task(monkeypatch, results, similar=(), username="nightowl_77", **options):
    monkeypatch.setattr(svc, "maigret", fake_maigret(results, similar))
    monkeypatch.setattr(svc, "_sites", lambda top: {"a": None, "b": None, "c": None})
    task = Task(
        service="maigret",
        input=Entity(type=EntityType.USERNAME, value=username),
        options=options,
    )
    events = []

    async def sink(event):
        events.append(event)

    final = await execute(svc.MaigretService(), task, sink)
    return events, final


def found(events):
    return [e for e in events if e.event is EventKind.ENTITY]


def test_manifest_is_valid():
    manifest = svc.MaigretService.get_manifest()
    assert manifest.name == "maigret"
    assert manifest.outputs == [EntityType.PROFILE, EntityType.IDENTITY, EntityType.IMAGE]
    assert manifest.option_default("top_sites") == 500


def test_bundled_site_database_loads_without_network():
    assert len(svc._sites(100)) >= 100
    assert len(svc._sites(0)) > 1000


async def test_bare_profile(monkeypatch):
    events, final = await run_task(
        monkeypatch,
        [
            claimed("GitHub", "https://github.com/nightowl_77"),
            MaigretCheckResult(
                "nightowl_77", "Reddit", "https://reddit.com/u/x", MaigretCheckStatus.AVAILABLE
            ),
        ],
    )
    assert final.event is EventKind.COMPLETED
    (profile,) = found(events)
    assert profile.entity.type is EntityType.PROFILE
    assert profile.entity.confidence == svc.CONFIDENCE
    assert profile.entity.attributes == {"site": "GitHub", "username": "nightowl_77"}


async def test_parsed_profile_yields_avatar_and_identity(monkeypatch):
    ids = {
        "fullname": "Night Owl",
        "bio": "I watch",
        "image": "https://avatars.example/n.png",
        "links": "https://nightowl.example.net",
        "uid": "12345",
        "follower_count": 42,
    }
    events, final = await run_task(
        monkeypatch, [claimed("GitHub", "https://github.com/nightowl_77", ids)]
    )
    assert final.count == 3
    profile, avatar, identity = found(events)

    attrs = profile.entity.attributes
    assert attrs["display_name"] == "Night Owl"
    assert attrs["bio"] == "I watch"
    assert attrs["avatar_url"] == "https://avatars.example/n.png"
    assert attrs["links"] == ["https://nightowl.example.net"]
    assert attrs["extra"] == {"uid": "12345", "follower_count": 42}
    assert profile.entity.confidence == svc.CONFIDENCE_PARSED

    assert avatar.entity.type is EntityType.IMAGE
    assert (avatar.link.from_, avatar.link.rel) == (profile.entity.id, "avatar")
    assert identity.entity.value == "Night Owl"
    assert (identity.link.from_, identity.link.rel) == (profile.entity.id, "identity")


async def test_similar_results_are_ignored(monkeypatch):
    events, final = await run_task(
        monkeypatch, [], similar=[claimed("Lookalike", "https://lookalike.example/nightowl")]
    )
    assert found(events) == []
    assert final.count == 0


async def test_identity_equal_to_username_is_skipped(monkeypatch):
    events, _ = await run_task(
        monkeypatch,
        [claimed("Site", "https://site.example/nightowl_77", {"fullname": "nightowl_77"})],
    )
    assert [e.entity.type for e in found(events)] == [EntityType.PROFILE]


async def test_rejects_unsupported_usernames(monkeypatch):
    _, final = await run_task(monkeypatch, [], username="a b")
    assert final.error.code is ErrorCode.INVALID_INPUT


async def test_maigret_crash_is_an_upstream_error(monkeypatch):
    async def broken(**kwargs):
        raise ConnectionError("network down")

    monkeypatch.setattr(svc, "maigret", broken)
    monkeypatch.setattr(svc, "_sites", lambda top: {})
    task = Task(service="maigret", input=Entity(type=EntityType.USERNAME, value="x"))

    async def sink(event):
        pass

    final = await execute(svc.MaigretService(), task, sink)
    assert final.error.code is ErrorCode.UPSTREAM_ERROR
