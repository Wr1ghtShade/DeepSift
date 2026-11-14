"""Gateway settings, read from environment variables."""

from __future__ import annotations

import os
import secrets
import stat
from dataclasses import dataclass, field
from pathlib import Path

TOKEN_FILE = "api-token"


def data_dir() -> Path:
    base = os.environ.get("DEEPSIFT_DATA_DIR") or Path.home() / ".local" / "share" / "deepsift"
    return Path(base)


def _read_secret(name: str) -> str | None:
    """``NAME`` or the content of the file named by ``NAME_FILE`` (Docker secrets)."""
    value = os.environ.get(name)
    if value:
        return value.strip()
    path = os.environ.get(f"{name}_FILE")
    if path:
        return Path(path).read_text(encoding="utf-8").strip() or None
    return None


def load_or_create_token(directory: Path) -> str:
    """The API token kept in ``<data dir>/api-token``, created on first start (mode 0600)."""
    path = directory / TOKEN_FILE
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    directory.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(token + "\n")
    return token


def database_url(directory: Path) -> str:
    """``DEEPSIFT_DATABASE_URL``, with ``DEEPSIFT_DATABASE_PASSWORD(_FILE)`` filled in;
    SQLite in the data directory when unset."""
    url = _read_secret("DEEPSIFT_DATABASE_URL")
    if not url:
        directory.mkdir(parents=True, exist_ok=True)
        return f"sqlite+aiosqlite:///{directory / 'deepsift.db'}"
    password = _read_secret("DEEPSIFT_DATABASE_PASSWORD")
    if password:
        from sqlalchemy.engine import make_url

        return make_url(url).set(password=password).render_as_string(hide_password=False)
    return url


def _split(value: str | None) -> list[str]:
    return [item.strip().rstrip("/") for item in (value or "").split(",") if item.strip()]


@dataclass
class Settings:
    """Everything the gateway needs to start.

    ``api_token``: ``DEEPSIFT_API_TOKEN`` (or ``DEEPSIFT_API_TOKEN_FILE``); without it the
    gateway creates one in the data directory and logs the file path, never the token.
    """

    database_url: str
    api_token: str
    redis_url: str | None = None
    allowed_origins: list[str] = field(default_factory=list)
    gui_dir: Path | None = None
    blobs_dir: Path | None = None
    session_ttl: int = 12 * 3600
    secure_cookies: bool = True
    hsts: bool = False
    token_file: Path | None = None

    @classmethod
    def from_env(cls) -> Settings:
        directory = data_dir()
        token = _read_secret("DEEPSIFT_API_TOKEN")
        token_file = None
        if not token:
            token = load_or_create_token(directory)
            token_file = directory / TOKEN_FILE
        gui = os.environ.get("DEEPSIFT_GUI_DIR")
        blobs = os.environ.get("DEEPSIFT_BLOBS_DIR")
        return cls(
            database_url=database_url(directory),
            api_token=token,
            redis_url=_read_secret("DEEPSIFT_REDIS_URL") or os.environ.get("REDIS_URL"),
            allowed_origins=_split(os.environ.get("DEEPSIFT_ALLOWED_ORIGINS")),
            gui_dir=Path(gui) if gui else None,
            blobs_dir=Path(blobs) if blobs else directory / "blobs",
            session_ttl=int(os.environ.get("DEEPSIFT_SESSION_TTL", 12 * 3600)),
            # Browsers accept Secure cookies on http://localhost, so this stays on.
            secure_cookies=os.environ.get("DEEPSIFT_INSECURE_COOKIES") != "1",
            hsts=os.environ.get("DEEPSIFT_HSTS") == "1",
            token_file=token_file,
        )
