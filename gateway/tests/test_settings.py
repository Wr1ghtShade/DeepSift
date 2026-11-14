from __future__ import annotations

from pathlib import Path

import pytest
from deepsift_gateway.settings import Settings


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in ("DEEPSIFT_API_TOKEN", "DEEPSIFT_DATABASE_URL", "REDIS_URL", "DEEPSIFT_REDIS_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DEEPSIFT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DEEPSIFT_ALLOWED_ORIGINS", "http://localhost:5173/, https://osint.lan")
    settings = Settings.from_env()
    assert settings.database_url == f"sqlite+aiosqlite:///{tmp_path / 'deepsift.db'}"
    assert settings.token_file == tmp_path / "api-token"
    assert settings.redis_url is None
    assert settings.allowed_origins == ["http://localhost:5173", "https://osint.lan"]
    assert settings.secure_cookies is True


def test_secrets_from_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "token").write_text("from-file\n", encoding="utf-8")
    (tmp_path / "pg").write_text("s3cr:et@\n", encoding="utf-8")
    monkeypatch.setenv("DEEPSIFT_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DEEPSIFT_API_TOKEN", raising=False)
    monkeypatch.setenv("DEEPSIFT_API_TOKEN_FILE", str(tmp_path / "token"))
    monkeypatch.setenv("DEEPSIFT_DATABASE_URL", "postgresql+asyncpg://deepsift@postgres/deepsift")
    monkeypatch.setenv("DEEPSIFT_DATABASE_PASSWORD_FILE", str(tmp_path / "pg"))
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    settings = Settings.from_env()
    assert settings.api_token == "from-file"
    assert settings.token_file is None
    assert settings.database_url == "postgresql+asyncpg://deepsift:s3cr%3Aet%40@postgres/deepsift"
    assert settings.redis_url == "redis://redis:6379/0"
