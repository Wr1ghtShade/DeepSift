from __future__ import annotations

import csv
import io

from fastapi.testclient import TestClient
from gwhelpers import ORIGIN, TOKEN, new_investigation, wait_run

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def test_run_merges_pivots_and_groups_avatars(api: TestClient) -> None:
    investigation = new_investigation(api)
    response = api.post(
        f"/api/v1/investigations/{investigation}/runs",
        json={
            "selector": "alice",
            "services": ["fake", "other-fake", "avatar-profiles"],
            "auto_pivot": True,
            "max_depth": 1,
        },
    )
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["type"] == "username"
    done = wait_run(api, run["id"])
    assert done["status"] == "completed"
    services = sorted(task["service"] for task in done["tasks"])
    # Three images found at depth 0 are hashed by fake-hash at depth 1.
    assert services.count("fake-hash") == 3
    assert all(task["status"] == "completed" for task in done["tasks"])

    entities = api.get(f"/api/v1/investigations/{investigation}/entities").json()
    by_value = {entity["value"]: entity for entity in entities}
    alice = by_value["https://example.org/u/alice"]
    assert sorted(s["service"] for s in alice["sources"]) == ["fake", "other-fake"]
    assert alice["score"] == 0.88  # noisy-OR of 0.6 and 0.7
    assert alice["level"] == "high"
    assert by_value["alice"]["selector"] is True

    site_a = by_value["https://site-a.example/alice"]
    site_b = by_value["https://site-b.example/alice"]
    site_c = by_value["https://site-c.example/alice"]
    assert site_a["avatar_group"] == site_b["avatar_group"] == "A"
    assert site_c["avatar_group"] is None
    assert site_a["score"] == 0.75  # 0.6 + avatar bonus

    filtered = api.get(
        f"/api/v1/investigations/{investigation}/entities",
        params={"min_confidence": 0.8, "type": "profile"},
    ).json()
    assert [e["value"] for e in filtered] == ["https://example.org/u/alice"]
    only_other = api.get(
        f"/api/v1/investigations/{investigation}/entities", params={"service": "other-fake"}
    ).json()
    assert {e["value"] for e in only_other} == {
        "https://example.org/u/alice",
        "https://other.example/alice",
    }

    graph = api.get(f"/api/v1/investigations/{investigation}/graph").json()
    rels = {(e["rel"]) for e in graph["edges"]}
    assert {"found_on", "avatar", "hash"} <= rels
    assert graph["avatar_groups"] == [{"name": "A", "profiles": [site_a["id"], site_b["id"]]}] or (
        graph["avatar_groups"][0]["name"] == "A"
        and sorted(graph["avatar_groups"][0]["profiles"]) == sorted([site_a["id"], site_b["id"]])
    )

    detail = api.get(f"/api/v1/entities/{site_a['id']}").json()
    assert detail["investigation_id"] == investigation
    rels = {(link["direction"], link["rel"]) for link in detail["links"]}
    assert ("in", "found_on") in rels and ("out", "avatar") in rels
    image = next(link for link in detail["links"] if link["rel"] == "avatar")
    assert image["entity"]["type"] == "image"

    summary = api.get(f"/api/v1/investigations/{investigation}").json()
    assert len(summary["runs"]) == 1
    listing = api.get("/api/v1/investigations").json()
    assert listing[0]["entities"] == len(entities)


def test_manual_pivot_runs_on_an_entity(api: TestClient) -> None:
    investigation = new_investigation(api)
    run = api.post(
        f"/api/v1/investigations/{investigation}/runs",
        json={"selector": "alice", "services": ["avatar-profiles"]},
    ).json()
    wait_run(api, run["id"])
    images = api.get(
        f"/api/v1/investigations/{investigation}/entities", params={"type": "image"}
    ).json()
    assert len(images) == 3 and all(not i["avatar_group"] for i in images)
    detail = api.get(f"/api/v1/entities/{images[0]['id']}").json()
    assert [p["service"] for p in detail["pivots"]] == ["fake-hash"]

    pivot = api.post(f"/api/v1/entities/{images[0]['id']}/pivot", json={})
    assert pivot.status_code == 201, pivot.text
    done = wait_run(api, pivot.json()["id"])
    assert [t["service"] for t in done["tasks"]] == ["fake-hash"]
    hashes = api.get(
        f"/api/v1/investigations/{investigation}/entities", params={"type": "image_hash"}
    ).json()
    assert len(hashes) == 1
    image = api.get(f"/api/v1/entities/{images[0]['id']}").json()
    assert image["selector"] is False


def test_default_plan_skips_opt_in_and_honours_toggles(api: TestClient) -> None:
    services = {s["name"]: s for s in api.get("/api/v1/services").json()}
    assert services["opt-in"]["enabled"] is False
    assert services["fake"]["enabled"] is True
    assert services["slow"]["options"]["behaviour"]["type"] == "enum"

    investigation = new_investigation(api)
    run = api.post(
        f"/api/v1/investigations/{investigation}/runs", json={"selector": "alice"}
    ).json()
    assert "opt-in" not in run["services"]
    assert "fake" in run["services"]
    wait_run(api, run["id"])

    assert api.patch("/api/v1/services/fake", json={"enabled": False}).json()["enabled"] is False
    assert api.patch("/api/v1/services/opt-in", json={"enabled": True}).status_code == 200
    run = api.post(f"/api/v1/investigations/{investigation}/runs", json={"selector": "bob"}).json()
    assert "fake" not in run["services"] and "opt-in" in run["services"]
    wait_run(api, run["id"])
    assert api.patch("/api/v1/services/nope", json={"enabled": True}).status_code == 404


def test_run_requests_are_validated(api: TestClient) -> None:
    investigation = new_investigation(api)
    url = f"/api/v1/investigations/{investigation}/runs"
    cases = [
        {"selector": "alice", "services": ["nope"]},
        {"selector": "alice", "services": ["fake-hash"]},  # takes images, not usernames
        {"selector": "alice", "options": {"slow": {"behaviour": "dance"}}},
        {"selector": "alice", "options": {"slow": {"unknown": 1}}},
        {"selector": "alice", "options": {"nope": {}}},
        {"selector": "alice", "type": "image_hash"},
        {"selector": "alice", "max_depth": 9},
        {"selector": ""},
    ]
    for body in cases:
        assert api.post(url, json=body).status_code == 422, body
    assert (
        api.post("/api/v1/investigations/missing/runs", json={"selector": "a"}).status_code == 404
    )


def test_failed_tasks_are_reported(api: TestClient) -> None:
    investigation = new_investigation(api)
    run = api.post(
        f"/api/v1/investigations/{investigation}/runs",
        json={
            "selector": "alice",
            "services": ["slow"],
            "options": {"slow": {"behaviour": "raise"}},
        },
    ).json()
    done = wait_run(api, run["id"])
    assert done["status"] == "completed"
    assert done["tasks"][0]["status"] == "failed"
    assert done["tasks"][0]["error"]["code"] == "internal"


def test_cancel_stops_a_run(api: TestClient) -> None:
    investigation = new_investigation(api)
    run = api.post(
        f"/api/v1/investigations/{investigation}/runs",
        json={
            "selector": "alice",
            "services": ["slow"],
            "options": {"slow": {"behaviour": "sleep"}},
        },
    ).json()
    response = api.post(f"/api/v1/runs/{run['id']}/cancel")
    assert response.status_code == 200
    done = api.get(f"/api/v1/runs/{run['id']}").json()
    assert done["status"] == "cancelled"
    assert done["tasks"][0]["status"] == "cancelled"
    assert api.post(f"/api/v1/runs/{run['id']}/cancel").status_code == 409
    assert api.post("/api/v1/runs/missing/cancel").status_code == 404


def test_exports(api: TestClient) -> None:
    investigation = new_investigation(api, "Case <1>")
    run = api.post(
        f"/api/v1/investigations/{investigation}/runs",
        json={"selector": "=cmd|' /C calc'!A0", "type": "username", "services": ["fake"]},
    ).json()
    wait_run(api, run["id"])
    base = f"/api/v1/investigations/{investigation}/export"

    report = api.get(base).json()
    assert report["investigation"]["name"] == "Case <1>"
    assert len(report["entities"]) == 2 and len(report["links"]) == 1

    exported = api.get(base, params={"format": "csv"})
    assert exported.headers["content-type"].startswith("text/csv")
    assert 'filename="deepsift-Case-1.csv"' in exported.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(exported.text)))
    selector = next(r for r in rows if r["type"] == "username")
    assert selector["value"].startswith("'=")

    page = api.get(base, params={"format": "html"})
    assert "<h1>Case &lt;1&gt;</h1>" in page.text
    csp = page.headers["content-security-policy"]
    assert csp.startswith("default-src 'none'; style-src 'sha256-")
    assert "<script" not in page.text
    assert api.get(base, params={"format": "pdf"}).status_code == 422


def test_blobs(api: TestClient) -> None:
    uploaded = api.post("/api/v1/blobs", content=PNG, headers={"Content-Type": "image/png"})
    assert uploaded.status_code == 201
    sha256 = uploaded.json()["sha256"]
    assert uploaded.json()["selector"] == f"blob:{sha256}"
    blob = api.get(f"/api/v1/blobs/{sha256}")
    assert blob.content == PNG
    assert blob.headers["content-type"] == "image/png"
    assert blob.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert blob.headers["x-content-type-options"] == "nosniff"
    html = b"<script>alert(1)</script>"
    assert api.post("/api/v1/blobs", content=html).status_code == 415
    assert api.get("/api/v1/blobs/../../etc/passwd").status_code == 404
    assert api.get("/api/v1/blobs/" + "0" * 64).status_code == 404


def test_delete_investigation(api: TestClient) -> None:
    investigation = new_investigation(api)
    run = api.post(
        f"/api/v1/investigations/{investigation}/runs",
        json={"selector": "alice", "services": ["fake"]},
    ).json()
    wait_run(api, run["id"])
    assert api.delete(f"/api/v1/investigations/{investigation}").status_code == 204
    assert api.get(f"/api/v1/investigations/{investigation}").status_code == 404
    assert api.get(f"/api/v1/runs/{run['id']}").status_code == 404


def test_websocket_stream(client: TestClient) -> None:
    client.post("/api/v1/session", json={"token": TOKEN}, headers={"Origin": ORIGIN})
    investigation = client.post(
        "/api/v1/investigations", json={"name": "live"}, headers={"Origin": ORIGIN}
    ).json()["id"]
    with client.websocket_connect(
        f"wss://testserver/api/v1/investigations/{investigation}/stream",
        headers={"Origin": ORIGIN},
    ) as socket:
        client.post(
            f"/api/v1/investigations/{investigation}/runs",
            json={"selector": "alice", "services": ["other-fake"]},
            headers={"Origin": ORIGIN},
        )
        kinds = []
        while True:
            message = socket.receive_json()
            kinds.append(message["type"])
            if message["type"] == "run.completed":
                break
    assert kinds[0] == "run.started"
    assert "task.queued" in kinds and "task.started" in kinds and "task.progress" in kinds
    assert kinds.count("task.entity") == 2
    assert "task.completed" in kinds


def test_websocket_refuses_strangers(client: TestClient) -> None:
    from starlette.websockets import WebSocketDisconnect

    investigation = client.post(
        "/api/v1/investigations",
        json={"name": "x"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    ).json()["id"]
    url = f"/api/v1/investigations/{investigation}/stream"
    for headers in ({}, {"Origin": "https://evil.example", "Authorization": f"Bearer {TOKEN}"}):
        try:
            with client.websocket_connect(url, headers=headers) as socket:
                socket.receive_json()
        except WebSocketDisconnect as exc:
            assert exc.code == 1008
        else:
            raise AssertionError("connection should have been refused")
