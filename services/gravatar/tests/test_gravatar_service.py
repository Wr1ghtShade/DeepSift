"""Unit tests: the Gravatar API is served by httpx.MockTransport."""

from __future__ import annotations

import deepsift_svc_gravatar as svc
import httpx
import pytest
from deepsift_sdk import Entity, EntityType, ErrorCode, EventKind, Task, execute

EMAIL = "Night.Owl@Example.org "
HASH = svc.email_hash(EMAIL)

PROFILE = {
    "hash": HASH,
    "display_name": "Night Owl",
    "profile_url": "https://gravatar.com/nightowl",
    "avatar_url": f"https://0.gravatar.com/avatar/{HASH}",
    "location": "Lille",
    "description": "I watch",
    "verified_accounts": [
        {"service_label": "GitHub", "url": "https://github.com/nightowl_77", "is_hidden": False},
        {"service_label": "Hidden", "url": "https://hidden.example/x", "is_hidden": True},
    ],
}


@pytest.fixture(autouse=True)
def no_key(monkeypatch):
    monkeypatch.delenv("GRAVATAR_API_KEY", raising=False)


async def run_task(monkeypatch, handler):
    seen = []

    def recording(request):
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(svc.GravatarService, "transport", httpx.MockTransport(recording))
    task = Task(service="gravatar", input=Entity(type=EntityType.EMAIL, value=EMAIL))
    events = []

    async def sink(event):
        events.append(event)

    final = await execute(svc.GravatarService(), task, sink)
    return events, final, seen


def entities(events):
    return [(e.entity, e.link) for e in events if e.event is EventKind.ENTITY]


def test_hash_follows_gravatar_rules():
    assert HASH == svc.email_hash("night.owl@example.org")
    assert len(HASH) == 64


async def test_full_profile(monkeypatch):
    events, final, seen = await run_task(monkeypatch, lambda r: httpx.Response(200, json=PROFILE))
    assert final.event is EventKind.COMPLETED
    found = entities(events)
    kinds = [(e.type, link.rel) for e, link in found]
    assert kinds == [
        (EntityType.PROFILE, "found_on"),
        (EntityType.IMAGE, "avatar"),
        (EntityType.IDENTITY, "identity"),
        (EntityType.PROFILE, "verified_account"),
    ]
    profile = found[0][0]
    assert profile.value == "https://gravatar.com/nightowl"
    assert profile.attributes["location"] == "Lille"
    assert found[3][0].value == "https://github.com/nightowl_77"
    assert found[3][1].from_ == profile.id
    assert str(seen[0].url) == svc.API + HASH
    assert "authorization" not in seen[0].headers


async def test_api_key_is_sent_when_set(monkeypatch):
    monkeypatch.setenv("GRAVATAR_API_KEY", "secret")
    _, _, seen = await run_task(monkeypatch, lambda r: httpx.Response(200, json=PROFILE))
    assert seen[0].headers["authorization"] == "Bearer secret"


async def test_avatar_without_public_profile(monkeypatch):
    def handler(request):
        if request.url.host == "api.gravatar.com":
            return httpx.Response(404)
        return httpx.Response(200)

    events, final, _ = await run_task(monkeypatch, handler)
    found = entities(events)
    assert [e.type for e, _ in found] == [EntityType.PROFILE, EntityType.IMAGE]
    assert found[1][0].value.startswith(svc.AVATAR + HASH)


async def test_nothing_found(monkeypatch):
    events, final, _ = await run_task(monkeypatch, lambda r: httpx.Response(404))
    assert final.event is EventKind.COMPLETED
    assert entities(events) == []


@pytest.mark.parametrize(
    ("status", "code"), [(429, ErrorCode.RATE_LIMITED), (503, ErrorCode.UPSTREAM_ERROR)]
)
async def test_errors(monkeypatch, status, code):
    _, final, _ = await run_task(monkeypatch, lambda r: httpx.Response(status))
    assert final.error.code is code
