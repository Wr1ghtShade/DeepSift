"""Cross-language checks: the Python bridge drives the real Node program.

No WhatsApp account is linked in tests, so the program must answer needs_config;
that exercises process spawning, the stdin task, stdout events and error mapping.
"""

from __future__ import annotations

import asyncio
import os
import shutil

import deepsift_svc_whatsapp as svc
import pytest
from deepsift_sdk import Entity, EntityType, ErrorCode, EventKind, Task, execute
from deepsift_sdk.local import LocalRun

NODE_READY = shutil.which("node") and (svc._SERVICE_DIR / "node_modules").is_dir()


def test_manifest_is_opt_in_and_serial():
    manifest = svc.WhatsAppService.get_manifest()
    assert manifest.name == "whatsapp"
    assert manifest.enabled_by_default is False
    assert manifest.concurrency == 1
    assert manifest.option_default("daily_limit") == 50


def test_off_unless_enabled():
    run = LocalRun({"whatsapp": svc.WhatsAppService()})
    assert run.plan(EntityType.PHONE) == []
    run = LocalRun({"whatsapp": svc.WhatsAppService()}, enabled={"whatsapp"})
    assert [s.manifest.name for s in run.plan(EntityType.PHONE)] == ["whatsapp"]


@pytest.mark.skipif(not NODE_READY, reason="node or services/whatsapp/node_modules missing")
async def test_bridge_reports_unlinked_account(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSIFT_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DEEPSIFT_WHATSAPP_CMD", raising=False)
    task = Task(
        service="whatsapp",
        input=Entity(type=EntityType.PHONE, value="+33612345678"),
        options={"min_interval": 0},
    )
    events = []

    async def sink(event):
        events.append(event)

    final = await execute(svc.WhatsAppService(), task, sink)
    assert final.event is EventKind.FAILED
    assert final.error.code is ErrorCode.NEEDS_CONFIG
    assert "deepsift-whatsapp link" in final.error.message
    limiter_state = tmp_path / "whatsapp" / "limiter.json"
    assert not await asyncio.to_thread(os.path.exists, limiter_state)  # quota untouched
