"""A gateway with fake services and the built GUI, for the browser check (e2e/check.mjs).

uv run python gui/e2e/server.py   # http://127.0.0.1:8800, token "e2e-token"
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sdk" / "tests"))

import uvicorn  # noqa: E402
from deepsift_gateway.api import create_app  # noqa: E402
from deepsift_gateway.executors import LocalExecutor  # noqa: E402
from deepsift_gateway.settings import Settings  # noqa: E402
from fakes import AvatarProfileService, FakeHashService, FakeService, OtherFakeService  # noqa: E402

services = {
    cls.get_manifest().name: cls()
    for cls in (FakeService, OtherFakeService, AvatarProfileService, FakeHashService)
}
data = Path(tempfile.mkdtemp(prefix="deepsift-e2e-"))
settings = Settings(
    database_url=f"sqlite+aiosqlite:///{data / 'db.sqlite'}",
    api_token="e2e-token",
    gui_dir=ROOT / "gui" / "dist",
    blobs_dir=data / "blobs",
)
uvicorn.run(
    create_app(settings, LocalExecutor(services)),
    host="127.0.0.1",
    port=8800,
    log_level="warning",
)
