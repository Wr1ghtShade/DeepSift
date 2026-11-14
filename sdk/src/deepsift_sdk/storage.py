"""Content-addressed blob storage (contract section 14)."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Protocol

_HEX = frozenset("0123456789abcdef")


def default_root() -> Path:
    """``$DEEPSIFT_DATA_DIR/blobs``, else ``~/.local/share/deepsift/blobs``."""
    base = os.environ.get("DEEPSIFT_DATA_DIR") or Path.home() / ".local" / "share" / "deepsift"
    return Path(base) / "blobs"


class Storage(Protocol):
    def put(self, data: bytes) -> str: ...

    def get(self, sha256: str) -> bytes | None: ...

    def exists(self, sha256: str) -> bool: ...


class LocalStorage:
    """Files named by their SHA-256 under ``<root>/<first 2 hex>/<sha256>``.

    Writing the same bytes twice stores them once.
    """

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else default_root()

    def _path(self, sha256: str) -> Path:
        if len(sha256) != 64 or not set(sha256) <= _HEX:
            raise ValueError("not a lower-case SHA-256 hex digest")
        return self.root / sha256[:2] / sha256

    def put(self, data: bytes) -> str:
        sha256 = hashlib.sha256(data).hexdigest()
        path = self._path(sha256)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
                tmp.write(data)
            os.replace(tmp.name, path)
        return sha256

    def get(self, sha256: str) -> bytes | None:
        path = self._path(sha256)
        return path.read_bytes() if path.exists() else None

    def exists(self, sha256: str) -> bool:
        return self._path(sha256).exists()
