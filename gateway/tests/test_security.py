from __future__ import annotations

from pathlib import Path

import pytest
from deepsift_gateway.api import create_app
from deepsift_gateway.executors import LocalExecutor
from deepsift_gateway.security import SESSION_COOKIE, origin_allowed
from deepsift_gateway.settings import load_or_create_token
from fastapi.testclient import TestClient
from gwhelpers import ORIGIN, TOKEN, make_services, make_settings


def test_health_is_public(client: TestClient) -> None:
    assert client.get("/api/v1/health").json() == {"status": "ok"}


def test_api_needs_credentials(client: TestClient) -> None:
    response = client.get("/api/v1/investigations")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    wrong = client.get("/api/v1/investigations", headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 401
    right = client.get("/api/v1/investigations", headers={"Authorization": f"Bearer {TOKEN}"})
    assert right.status_code == 200


def test_session_cookie_login_and_logout(client: TestClient) -> None:
    response = client.post("/api/v1/session", json={"token": TOKEN}, headers={"Origin": ORIGIN})
    assert response.status_code == 204
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    for attribute in ("HttpOnly", "Secure", "SameSite=strict", "Path=/"):
        assert attribute.lower() in cookie.lower()
    assert "domain" not in cookie.lower()

    assert client.get("/api/v1/session").json() == {"authenticated": True}
    assert client.get("/api/v1/investigations").status_code == 200

    # State-changing requests with a cookie need an allowed Origin (CSRF).
    no_origin = client.post("/api/v1/investigations", json={"name": "x"})
    assert no_origin.status_code == 403
    evil = client.post(
        "/api/v1/investigations", json={"name": "x"}, headers={"Origin": "https://evil.example"}
    )
    assert evil.status_code == 403
    ok = client.post("/api/v1/investigations", json={"name": "x"}, headers={"Origin": ORIGIN})
    assert ok.status_code == 201

    out = client.delete("/api/v1/session")
    assert out.status_code == 204
    assert out.headers["clear-site-data"] == '"cookies", "storage", "cache"'
    assert client.get("/api/v1/session").json() == {"authenticated": False}


def test_login_is_throttled(client: TestClient) -> None:
    for _ in range(5):
        assert client.post("/api/v1/session", json={"token": "bad"}).status_code == 401
    assert client.post("/api/v1/session", json={"token": TOKEN}).status_code == 429


def test_login_from_another_site_is_refused(client: TestClient) -> None:
    response = client.post(
        "/api/v1/session",
        json={"token": TOKEN},
        headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "same-site"},
    )
    assert response.status_code == 403


def test_security_headers_on_api(api: TestClient) -> None:
    headers = api.get("/api/v1/investigations").headers
    assert headers["content-security-policy"].startswith("default-src 'none'")
    assert "frame-ancestors 'none'" in headers["content-security-policy"]
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "no-referrer"
    assert headers["cross-origin-opener-policy"] == "same-origin"
    assert headers["cross-origin-resource-policy"] == "same-origin"
    assert headers["cache-control"] == "no-store"
    assert "camera=()" in headers["permissions-policy"]
    assert "Sec-Fetch-Site" in headers["vary"]
    assert "server" not in headers or "uvicorn" not in headers["server"]


def test_fetch_metadata_blocks_cross_site_api_calls(api: TestClient) -> None:
    response = api.get("/api/v1/investigations", headers={"Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 403
    assert (
        api.get("/api/v1/investigations", headers={"Sec-Fetch-Site": "same-origin"}).status_code
        == 200
    )


def test_body_size_is_capped(api: TestClient) -> None:
    response = api.post(
        "/api/v1/investigations",
        content=b"{" + b" " * (2 << 20) + b"}",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413


def test_validation_limits(api: TestClient) -> None:
    assert api.post("/api/v1/investigations", json={"name": ""}).status_code == 422
    assert api.post("/api/v1/investigations", json={"name": "x" * 201}).status_code == 422


def test_origin_allowed() -> None:
    assert origin_allowed("https://host:8000", "host:8000", [])
    assert origin_allowed("http://localhost:5173", "gw:8000", ["http://localhost:5173"])
    assert not origin_allowed("https://host.evil:8000", "host:8000", [])
    assert not origin_allowed("null", "host", [])
    assert not origin_allowed(None, "host", [])


def test_token_file_is_private(tmp_path: Path) -> None:
    token = load_or_create_token(tmp_path)
    assert len(token) >= 40
    assert (tmp_path / "api-token").stat().st_mode & 0o777 == 0o600
    assert load_or_create_token(tmp_path) == token


def test_reports_endpoint_accepts_csp_reports(client: TestClient) -> None:
    report = [
        {
            "type": "csp-violation",
            "body": {
                "effectiveDirective": "script-src-elem",
                "blockedURL": "https://evil.example/x.js?secret=1",
            },
        }
    ]
    response = client.post(
        "/api/v1/reports", json=report, headers={"Content-Type": "application/reports+json"}
    )
    assert response.status_code == 204


@pytest.fixture
def gui_client(tmp_path: Path):
    gui = tmp_path / "gui"
    (gui / "assets").mkdir(parents=True)
    (gui / "index.html").write_text(
        '<!doctype html><script type="module" nonce="__CSP_NONCE__" src="/assets/app.js"></script>',
        encoding="utf-8",
    )
    (gui / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("nope", encoding="utf-8")
    app = create_app(make_settings(tmp_path, gui_dir=gui), LocalExecutor(make_services()))
    with TestClient(app, base_url=ORIGIN) as test_client:
        yield test_client


def test_gui_shell_gets_a_fresh_nonce(gui_client: TestClient) -> None:
    first = gui_client.get("/")
    second = gui_client.get("/investigations/123")
    assert first.status_code == second.status_code == 200
    csp = first.headers["content-security-policy"]
    nonce = csp.split("'nonce-")[1].split("'")[0]
    assert f'nonce="{nonce}"' in first.text
    assert "__CSP_NONCE__" not in first.text
    assert nonce not in second.text
    for directive in (
        "'strict-dynamic'",
        "object-src 'none'",
        "base-uri 'none'",
        "require-trusted-types-for 'script'",
        "report-to csp",
    ):
        assert directive in csp
    assert first.headers["cache-control"] == "no-cache"


def test_gui_assets_are_immutable_and_paths_stay_inside(gui_client: TestClient) -> None:
    asset = gui_client.get("/assets/app.js")
    assert asset.status_code == 200
    assert "immutable" in asset.headers["cache-control"]
    assert asset.headers["content-type"].startswith("text/javascript")
    leaked = gui_client.get("/../secret.txt")
    assert "nope" not in leaked.text
    assert gui_client.get("/api/v1/unknown").status_code in (401, 404)
