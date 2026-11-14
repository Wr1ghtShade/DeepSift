from __future__ import annotations

import json

from deepsift_cli import main
from fakes import FakeService, OtherFakeService
from typer.testing import CliRunner

runner = CliRunner()


def fake_discover():
    return {"fake": FakeService, "other-fake": OtherFakeService}


def test_user_runs_services_and_merges_findings(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "discover", fake_discover)
    out = tmp_path / "findings.json"
    result = runner.invoke(main.app, ["user", "alice", "--output", str(out)])
    assert result.exit_code == 0, result.output
    assert "https://example.org/u/alice" in result.output
    assert "high (0.88)" in result.output
    saved = json.loads(out.read_text())
    assert saved["selector"]["type"] == "username"
    assert saved["findings"][0]["score"] == 0.88
    assert saved["findings"][0]["sources"] == {"fake": 0.6, "other-fake": 0.7}


def test_min_level_hides_low_findings(monkeypatch):
    monkeypatch.setattr(main, "discover", fake_discover)
    result = runner.invoke(main.app, ["user", "alice", "--min", "medium"])
    assert result.exit_code == 0, result.output
    assert "other.example" not in result.output


def test_unknown_service_is_an_error(monkeypatch):
    monkeypatch.setattr(main, "discover", fake_discover)
    result = runner.invoke(main.app, ["user", "alice", "-s", "nope"])
    assert result.exit_code == 2
    assert "unknown service" in result.output


def test_selector_type_with_no_service(monkeypatch):
    monkeypatch.setattr(main, "discover", fake_discover)
    result = runner.invoke(main.app, ["search", "john@example.org"])
    assert result.exit_code == 0
    assert "No installed service accepts email" in result.output


def test_services_lists_installed(monkeypatch):
    monkeypatch.setattr(main, "discover", fake_discover)
    result = runner.invoke(main.app, ["services"])
    assert result.exit_code == 0
    assert "fake" in result.output
    assert "ready" in result.output
