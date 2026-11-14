"""Unit tests: SearXNG's JSON API is served by httpx.MockTransport."""

from __future__ import annotations

import deepsift_svc_searxng as svc
import httpx
import pytest
from deepsift_sdk import Entity, EntityType, ErrorCode, EventKind, Task, execute
from deepsift_sdk.local import LocalRun

BASE = "http://searxng.test:8080"


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setenv("SEARXNG_URL", BASE + "/")


def page(*results, unresponsive=()):
    return {
        "results": list(results),
        "unresponsive_engines": [[e, "timeout"] for e in unresponsive],
    }


def result(url, title="", content="", engines=("duckduckgo",)):
    return {"url": url, "title": title, "content": content, "engines": list(engines)}


async def run(monkeypatch, entity_type, value, handler, **options):
    seen = []

    def recording(request):
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(svc.SearxngService, "transport", httpx.MockTransport(recording))
    task = Task(service="searxng", input=Entity(type=entity_type, value=value), options=options)
    events = []

    async def sink(event):
        events.append(event)

    final = await execute(svc.SearxngService(), task, sink)
    found = [e.entity for e in events if e.event is EventKind.ENTITY]
    return final, found, events, seen


def test_queries():
    assert svc.queries_for(EntityType.USERNAME, "nightowl_77", True) == ['"nightowl_77"']
    assert svc.queries_for(EntityType.DOMAIN, "example.fr", True) == [
        '"example.fr" -site:example.fr'
    ]
    assert svc.queries_for(EntityType.PHONE, "+33612345678", True) == [
        '"+33612345678"',
        '"+33 6 12 34 56 78"',
        '"06 12 34 56 78"',
    ]
    assert svc.queries_for(EntityType.PHONE, "+33612345678", False) == ['"+33612345678"']


async def test_keeps_pages_that_mention_the_selector(monkeypatch):
    data = page(
        result(
            "https://forum.example/u/nightowl_77", "nightowl_77 profile", "posts by nightowl_77"
        ),
        result("https://news.example/owls", "Owls at night", "nothing relevant"),
        result("https://forum.example/u/nightowl_77", "duplicate"),
        unresponsive=("google",),
    )
    final, found, events, seen = await run(
        monkeypatch, EntityType.USERNAME, "nightowl_77", lambda r: httpx.Response(200, json=data)
    )
    assert final.event is EventKind.COMPLETED
    assert [p.value for p in found] == ["https://forum.example/u/nightowl_77"]
    assert found[0].confidence == svc.MENTIONED
    assert found[0].attributes["site"] == "forum.example"
    assert found[0].attributes["engines"] == ["duckduckgo"]
    request = seen[0]
    assert str(request.url).startswith(BASE + "/search?")
    assert request.url.params["format"] == "json"
    assert request.url.params["q"] == '"nightowl_77"'
    assert any("google" in (e.message or "") for e in events)


async def test_loose_results_on_request(monkeypatch):
    data = page(result("https://news.example/owls", "Owls"))
    _, found, _, _ = await run(
        monkeypatch,
        EntityType.USERNAME,
        "nightowl_77",
        lambda r: httpx.Response(200, json=data),
        include_unmentioned=True,
    )
    assert found[0].confidence == svc.LOOSE


async def test_phone_matches_any_spelling_and_runs_each_variant(monkeypatch):
    data = page(result("https://annuaire.example/x", "Contact", "Tél. 06 12 34 56 78"))
    _, found, _, seen = await run(
        monkeypatch, EntityType.PHONE, "+33612345678", lambda r: httpx.Response(200, json=data)
    )
    assert len(seen) == 3
    assert [p.value for p in found] == ["https://annuaire.example/x"]


async def test_max_results(monkeypatch):
    data = page(*(result(f"https://e.example/{i}", "alice", "alice") for i in range(10)))
    _, found, _, _ = await run(
        monkeypatch,
        EntityType.USERNAME,
        "alice",
        lambda r: httpx.Response(200, json=data),
        max_results=3,
    )
    assert len(found) == 3


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(403), ErrorCode.NEEDS_CONFIG),
        (httpx.Response(429), ErrorCode.RATE_LIMITED),
        (httpx.Response(502), ErrorCode.UPSTREAM_ERROR),
        (httpx.Response(200, text="<html>"), ErrorCode.UPSTREAM_ERROR),
    ],
)
async def test_errors(monkeypatch, response, code):
    final, _, _, _ = await run(monkeypatch, EntityType.USERNAME, "alice", lambda r: response)
    assert final.error.code is code


async def test_unreachable_instance_explains_how_to_start_it(monkeypatch):
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    final, _, _, _ = await run(monkeypatch, EntityType.USERNAME, "alice", refuse)
    assert final.error.code is ErrorCode.UPSTREAM_ERROR
    assert "docker compose up -d searxng" in final.error.message


def test_skipped_without_searxng_url(monkeypatch):
    monkeypatch.delenv("SEARXNG_URL")
    assert LocalRun({"searxng": svc.SearxngService()}).plan(EntityType.USERNAME) == []
