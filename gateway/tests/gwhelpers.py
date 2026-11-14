from __future__ import annotations

import time
from pathlib import Path

from deepsift_gateway.settings import Settings
from fakes import (
    AvatarProfileService,
    FakeHashService,
    FakeService,
    OtherFakeService,
    make_manifest,
)
from fastapi.testclient import TestClient

TOKEN = "test-token-0123456789"
ORIGIN = "https://testserver"


class SlowService(FakeService):
    """Like FakeService, with its ``behaviour`` option declared so the gateway accepts it."""

    _manifest = make_manifest(
        "slow",
        options={"behaviour": {"type": "enum", "values": ["sleep", "raise", "ok"]}},
    )


class OptInService(FakeService):
    _manifest = make_manifest("opt-in", enabled_by_default=False)


def make_services() -> dict:
    classes = [
        FakeService,
        OtherFakeService,
        AvatarProfileService,
        FakeHashService,
        SlowService,
        OptInService,
    ]
    return {cls.get_manifest().name: cls() for cls in classes}


def make_settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "database_url": f"sqlite+aiosqlite:///{tmp_path / 'gateway.db'}",
        "api_token": TOKEN,
        "blobs_dir": tmp_path / "blobs",
    }
    values.update(overrides)
    return Settings(**values)


def wait_run(client: TestClient, run_id: str, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = client.get(f"/api/v1/runs/{run_id}").json()
        if run["status"] != "running":
            return run
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} still running")


def new_investigation(client: TestClient, name: str = "Case") -> str:
    response = client.post("/api/v1/investigations", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]
