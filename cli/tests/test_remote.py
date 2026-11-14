"""The CLI in gateway mode, against a real gateway on localhost with fake services."""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn
from deepsift_cli import main
from deepsift_gateway.api import create_app
from deepsift_gateway.executors import LocalExecutor
from deepsift_gateway.settings import Settings
from fakes import AvatarProfileService, FakeHashService, FakeService, OtherFakeService
from rich.console import Console
from typer.testing import CliRunner

TOKEN = "cli-test-token"
runner = CliRunner()


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def gateway_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    data: Path = tmp_path_factory.mktemp("gateway")
    services = {
        cls.get_manifest().name: cls()
        for cls in (FakeService, OtherFakeService, AvatarProfileService, FakeHashService)
    }
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{data / 'db.sqlite'}",
        api_token=TOKEN,
        blobs_dir=data / "blobs",
    )
    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(settings, LocalExecutor(services)),
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(autouse=True)
def setup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "console", Console(width=220))
    monkeypatch.setenv("DEEPSIFT_API_TOKEN", TOKEN)
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY"):
        monkeypatch.delenv(name, raising=False)


def test_user_through_the_gateway(gateway_url: str, tmp_path: Path) -> None:
    out = tmp_path / "findings.json"
    result = runner.invoke(
        main.app,
        [
            "--gateway",
            gateway_url,
            "user",
            "alice",
            "-s",
            "avatar-profiles",
            "-s",
            "fake",
            "-s",
            "other-fake",
            "-o",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "The sieve" in result.output
    assert "fake-hash" in result.output  # pivot on the avatars, run by the gateway
    assert "Avatar A: same picture on" in result.output
    assert "kept on the gateway" in result.output
    payload = json.loads(out.read_text())
    alice = next(
        f for f in payload["findings"] if f["entity"]["value"] == "https://example.org/u/alice"
    )
    assert sorted(alice["sources"]) == ["fake", "other-fake"]
    assert alice["score"] == 0.88
    assert payload["selector"]["value"] == "alice"
    assert any(link["rel"] == "avatar" for link in payload["links"])


def test_services_through_the_gateway(gateway_url: str) -> None:
    result = runner.invoke(main.app, ["--gateway", gateway_url, "services"])
    assert result.exit_code == 0, result.output
    assert "avatar-profiles" in result.output and "ready" in result.output


def test_options_are_checked_against_the_gateway(gateway_url: str) -> None:
    result = runner.invoke(
        main.app, ["--gateway", gateway_url, "user", "alice", "--opt", "fake.nope=1"]
    )
    assert result.exit_code == 2
    assert "has no option" in result.output


def test_bad_token_is_reported(gateway_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSIFT_API_TOKEN", "wrong")
    result = runner.invoke(main.app, ["--gateway", gateway_url, "services"])
    assert result.exit_code == 1
    assert "refused the API token" in result.output


def test_missing_token(gateway_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("DEEPSIFT_API_TOKEN")
    monkeypatch.setenv("DEEPSIFT_DATA_DIR", str(tmp_path))
    result = runner.invoke(main.app, ["--gateway", gateway_url, "services"])
    assert result.exit_code == 2
    assert "No API token" in result.output


def test_token_from_the_local_gateway_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from deepsift_cli.remote import find_token

    monkeypatch.delenv("DEEPSIFT_API_TOKEN")
    monkeypatch.delenv("DEEPSIFT_API_TOKEN_FILE", raising=False)
    monkeypatch.setenv("DEEPSIFT_DATA_DIR", str(tmp_path))
    (tmp_path / "api-token").write_text("local-secret\n")
    assert find_token("http://127.0.0.1:8000") == "local-secret"
    assert find_token("https://osint.example") is None
