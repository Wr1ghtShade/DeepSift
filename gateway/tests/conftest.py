from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from deepsift_gateway.api import create_app
from deepsift_gateway.executors import LocalExecutor
from deepsift_gateway.settings import Settings
from fastapi.testclient import TestClient
from gwhelpers import ORIGIN, TOKEN, make_services, make_settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings, LocalExecutor(make_services()))
    with TestClient(app, base_url=ORIGIN) as test_client:
        yield test_client


@pytest.fixture
def api(client: TestClient) -> TestClient:
    """A client authenticated with the bearer token."""
    client.headers["Authorization"] = f"Bearer {TOKEN}"
    return client
