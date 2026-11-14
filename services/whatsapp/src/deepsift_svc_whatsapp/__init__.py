"""Python bridge to the WhatsApp service, which is written in Node (Baileys).

In the stack, the Node program talks to Redis itself (``deepsift-whatsapp worker``).
In local mode, the CLI runs it per task over stdin/stdout through ``ExternalService``.

The program is looked up in this order:
``DEEPSIFT_WHATSAPP_CMD`` (shell syntax), ``deepsift-whatsapp`` on the PATH, then the
copy in this repository when it has its ``node_modules``.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from deepsift_sdk.external import ExternalService
from deepsift_sdk.manifest import Manifest, load_manifest

__all__ = ["WhatsAppService"]

_HERE = Path(__file__).resolve().parent
#: services/whatsapp/, when running from a clone of the repository.
_SERVICE_DIR = _HERE.parent.parent


class WhatsAppService(ExternalService):
    command = ("deepsift-whatsapp", "stdio")
    install_hint = "cd services/whatsapp && npm ci && npm link"

    @classmethod
    def get_manifest(cls) -> Manifest:
        if cls.__dict__.get("_manifest") is None:
            packaged = _HERE / "manifest.yaml"
            cls._manifest = load_manifest(
                packaged if packaged.exists() else _SERVICE_DIR / "manifest.yaml"
            )
        return cls._manifest  # type: ignore[return-value]

    @classmethod
    def resolve_command(cls) -> list[str]:
        script = _SERVICE_DIR / "src" / "cli.js"
        in_repo = (_SERVICE_DIR / "node_modules").is_dir() and script.is_file()
        if shutil.which(cls.command[0]) is None and in_repo and shutil.which("node"):
            import os

            if not os.environ.get("DEEPSIFT_WHATSAPP_CMD"):
                return ["node", str(script), "stdio"]
        return super().resolve_command()
