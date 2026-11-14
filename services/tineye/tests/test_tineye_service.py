"""Unit tests: the TinEye API is served by httpx.MockTransport."""

from __future__ import annotations

import deepsift_svc_tineye as svc
import httpx
import pytest
from deepsift_sdk import Entity, EntityType, ErrorCode, EventKind, Task, execute
from deepsift_sdk.local import LocalRun

BODY = {
    "code": 200,
    "messages": [],
    "stats": {"total_remaining_searches": 4321},
    "results": {
        "total_results": 2,
        "matches": [
            {
                "image_url": "https://img.tineye.com/a.jpg",
                "domain": "photos.example",
                "score": 88.5,
                "width": 400,
                "height": 400,
                "tags": ["stock"],
                "backlinks": [
                    {
                        "url": "https://photos.example/a.jpg",
                        "backlink": "https://photos.example/gallery/7",
                        "crawl_date": "2014-03-02",
                    },
                    {
                        "url": "https://photos.example/a.jpg",
                        "backlink": "https://photos.example/gallery/8",
                        "crawl_date": "2016-01-01",
                    },
                ],
            },
            {
                "image_url": "https://img.tineye.com/b.jpg",
                "domain": "blog.example",
                "score": 40,
                "backlinks": [
                    {
                        "url": "https://blog.example/b.jpg",
                        "backlink": "https://blog.example/post",
                        "crawl_date": "2019-05-05",
                    }
                ],
            },
        ],
    },
}


@pytest.fixture(autouse=True)
def keyed(monkeypatch, tmp_path):
    monkeypatch.setenv("TINEYE_API_KEY", "secret-key")
    monkeypatch.setenv("DEEPSIFT_DATA_DIR", str(tmp_path))


async def run(monkeypatch, value, handler, **options):
    seen = []

    def recording(request):
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(svc.TinEyeService, "transport", httpx.MockTransport(recording))
    service = svc.TinEyeService()
    if value == "BLOB":
        value = "blob:" + service.storage.put(b"\xff\xd8 fake jpeg")
    task = Task(service="tineye", input=Entity(type=EntityType.IMAGE, value=value), options=options)
    events = []

    async def sink(event):
        events.append(event)

    final = await execute(service, task, sink)
    found = [e.entity for e in events if e.event is EventKind.ENTITY]
    return final, found, events, seen


async def test_search_by_url(monkeypatch):
    final, found, events, seen = await run(
        monkeypatch, "https://pps.example/avatar.jpg", lambda r: httpx.Response(200, json=BODY)
    )
    assert final.event is EventKind.COMPLETED
    request = seen[0]
    assert request.method == "GET"
    assert request.headers["x-api-key"] == "secret-key"
    assert request.url.params["image_url"] == "https://pps.example/avatar.jpg"
    assert [p.value for p in found] == [
        "https://photos.example/gallery/7",
        "https://photos.example/gallery/8",
        "https://blog.example/post",
    ]
    first = found[0]
    assert first.attributes["crawl_date"] == "2014-03-02"
    assert first.attributes["site"] == "photos.example"
    assert first.attributes["tags"] == ["stock"]
    note = [e.message for e in events if e.message][-1]
    assert "first seen 2014-03-02 on photos.example" in note
    assert "4321 TinEye searches left" in note


async def test_blob_is_uploaded(monkeypatch):
    final, _, _, seen = await run(monkeypatch, "BLOB", lambda r: httpx.Response(200, json=BODY))
    assert final.event is EventKind.COMPLETED
    request = seen[0]
    assert request.method == "POST"
    assert b'name="image_upload"' in request.content
    assert b"fake jpeg" in request.content


async def test_backlinks_per_match(monkeypatch):
    _, found, _, _ = await run(
        monkeypatch,
        "https://pps.example/a.jpg",
        lambda r: httpx.Response(200, json=BODY),
        backlinks_per_match=1,
    )
    assert len(found) == 2


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(401, json={"code": 401, "messages": ["bad key"]}), ErrorCode.NEEDS_CONFIG),
        (
            httpx.Response(200, json={"code": 400, "messages": ["No remaining searches"]}),
            ErrorCode.RATE_LIMITED,
        ),
        (
            httpx.Response(400, json={"code": 400, "messages": ["Couldn't download URL."]}),
            ErrorCode.INVALID_INPUT,
        ),
        (httpx.Response(503), ErrorCode.UPSTREAM_ERROR),
    ],
)
async def test_errors(monkeypatch, response, code):
    final, _, _, _ = await run(monkeypatch, "https://pps.example/a.jpg", lambda r: response)
    assert final.error.code is code


async def test_rejects_other_values(monkeypatch):
    final, _, _, seen = await run(monkeypatch, "blob:" + "0" * 64, lambda r: httpx.Response(200))
    assert final.error.code is ErrorCode.INVALID_INPUT
    assert seen == []


def test_skipped_without_key(monkeypatch):
    monkeypatch.delenv("TINEYE_API_KEY")
    assert LocalRun({"tineye": svc.TinEyeService()}).plan(EntityType.IMAGE) == []
