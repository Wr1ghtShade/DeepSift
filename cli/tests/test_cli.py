from __future__ import annotations

import json

import pytest
from deepsift_cli import main
from deepsift_sdk import Entity, EntityType
from fakes import FakeService, OtherFakeService
from rich.console import Console
from typer.testing import CliRunner

runner = CliRunner()


@pytest.fixture(autouse=True)
def wide_console(monkeypatch):
    """A wide terminal, so URLs are not folded across lines in the output."""
    monkeypatch.setattr(main, "console", Console(width=220))


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


def test_avatar_groups_show_in_table_and_json(monkeypatch, tmp_path):
    from fakes import AvatarProfileService, FakeHashService

    monkeypatch.setattr(
        main,
        "discover",
        lambda: {"avatar-profiles": AvatarProfileService, "fake-hash": FakeHashService},
    )
    out = tmp_path / "findings.json"
    result = runner.invoke(main.app, ["user", "alice", "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert "Avatar A: same picture on" in result.output
    assert "phash:" not in result.output  # correlation entities stay out of the table
    saved = json.loads(out.read_text())
    assert saved["avatar_groups"][0]["name"] == "A"
    assert any(link["rel"] == "avatar" for link in saved["links"])
    grouped = [f for f in saved["findings"] if f["avatar_group"] == "A"]
    assert len(grouped) == 2
    assert all(f["score"] == 0.75 for f in grouped)


def test_depth_zero_skips_pivots(monkeypatch):
    from fakes import AvatarProfileService, FakeHashService

    monkeypatch.setattr(
        main,
        "discover",
        lambda: {"avatar-profiles": AvatarProfileService, "fake-hash": FakeHashService},
    )
    result = runner.invoke(main.app, ["user", "alice", "--depth", "0"])
    assert result.exit_code == 0, result.output
    assert "fake-hash" not in result.output
    assert "Avatar A" not in result.output


def test_opt_reaches_the_service_typed_by_its_manifest(monkeypatch):
    from fakes import FakeService, make_manifest

    seen = {}

    class Configurable(FakeService):
        _manifest = make_manifest(
            "conf",
            options={
                "top": {"type": "int", "default": 5},
                "deep": {"type": "bool", "default": False},
                "mode": {"type": "enum", "values": ["a", "b"], "default": "a"},
            },
        )

        async def run(self, task, ctx):
            seen.update(top=ctx.option("top"), deep=ctx.option("deep"), mode=ctx.option("mode"))

    monkeypatch.setattr(main, "discover", lambda: {"conf": Configurable})
    args = [
        "user",
        "alice",
        "--opt",
        "conf.top=0",
        "--opt",
        "conf.deep=yes",
        "--opt",
        "conf.mode=b",
    ]
    result = runner.invoke(main.app, args)
    assert result.exit_code == 0, result.output
    assert seen == {"top": 0, "deep": True, "mode": "b"}


@pytest.mark.parametrize(
    ("opt", "message"),
    [
        ("fake.nope=1", "has no option"),
        ("ghost.top=1", "unknown service"),
        ("fake", "service.option=value"),
    ],
)
def test_bad_opt_is_an_error(monkeypatch, opt, message):
    monkeypatch.setattr(main, "discover", fake_discover)
    result = runner.invoke(main.app, ["user", "alice", "--opt", opt])
    assert result.exit_code == 2
    assert message in result.output


def test_region_fills_default_region_where_declared(monkeypatch):
    from fakes import FakeService, make_manifest

    seen = {}

    class Phoney(FakeService):
        _manifest = make_manifest(
            "phoney",
            inputs=["phone"],
            options={"default_region": {"type": "str", "default": ""}},
        )

        async def run(self, task, ctx):
            seen["region"] = ctx.option("default_region")

    monkeypatch.setattr(main, "discover", lambda: {"phoney": Phoney, "fake": FakeService})
    result = runner.invoke(main.app, ["phone", "0612345678", "--region", "fr"])
    assert result.exit_code == 0, result.output
    assert seen == {"region": "FR"}
    result = runner.invoke(main.app, ["phone", "0612345678", "--region", "France"])
    assert result.exit_code == 2


@pytest.mark.parametrize(
    ("entity", "expected"),
    [
        (
            Entity(
                type=EntityType.PHONE_META,
                value="+33612345678",
                attributes={
                    "international": "+33 6 12 34 56 78",
                    "country_name": "France",
                    "line_type": "mobile",
                    "carrier": "Orange",
                    "valid": True,
                },
            ),
            ("phone", "+33 6 12 34 56 78 (France, mobile, first carrier Orange)"),
        ),
        (
            Entity(
                type=EntityType.MX_RECORD,
                value="aspmx.l.google.com",
                attributes={"priority": 1, "provider": "Google Workspace"},
            ),
            ("mail server", "aspmx.l.google.com (priority 1, Google Workspace)"),
        ),
        (
            Entity(
                type=EntityType.ACCOUNT,
                value="github.com:a@b.org",
                attributes={"site": "github.com"},
            ),
            ("github.com", "registered"),
        ),
    ],
)
def test_describe(entity, expected):
    assert main.describe(entity) == expected


def test_enable_turns_on_opt_in_services(monkeypatch):
    from fakes import FakeService, make_manifest

    class OptIn(FakeService):
        _manifest = make_manifest("opt-in", enabled_by_default=False)

    monkeypatch.setattr(main, "discover", lambda: {"fake": FakeService, "opt-in": OptIn})
    result = runner.invoke(main.app, ["user", "alice"])
    assert "opt-in" not in result.output
    result = runner.invoke(main.app, ["user", "alice", "--enable", "opt-in"])
    assert result.exit_code == 0, result.output
    assert "opt-in" in result.output
    result = runner.invoke(main.app, ["services"])
    assert "off by default (--enable opt-in)" in result.output
    result = runner.invoke(main.app, ["user", "alice", "--enable", "ghost"])
    assert result.exit_code == 2


def test_services_lists_installed(monkeypatch):
    monkeypatch.setattr(main, "discover", fake_discover)
    result = runner.invoke(main.app, ["services"])
    assert result.exit_code == 0
    assert "fake" in result.output
    assert "ready" in result.output
