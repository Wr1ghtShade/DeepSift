"""phonenumbers is offline: these tests use the real library."""

from __future__ import annotations

import deepsift_svc_phone_meta as svc
import pytest
from deepsift_sdk import Entity, EntityType, ErrorCode, EventKind, Task, execute


async def run_task(value, **options):
    task = Task(
        service="phone-meta", input=Entity(type=EntityType.PHONE, value=value), options=options
    )
    events = []

    async def sink(event):
        events.append(event)

    final = await execute(svc.PhoneMetaService(), task, sink)
    found = [e.entity for e in events if e.event is EventKind.ENTITY]
    return events, final, found


async def test_french_mobile():
    _, final, (meta,) = await run_task("+33 6 12 34 56 78")
    assert final.event is EventKind.COMPLETED
    assert meta.type is EntityType.PHONE_META
    assert meta.value == "+33612345678"
    attrs = meta.attributes
    assert attrs["country"] == "FR"
    assert attrs["line_type"] == "mobile"
    assert attrs["valid"] is True
    assert attrs["national"] == "06 12 34 56 78"
    assert attrs["time_zones"] == ["Europe/Paris"]


async def test_french_landline_has_an_area():
    _, _, (meta,) = await run_task("+33320123456", lang="fr")
    assert meta.attributes["line_type"] == "fixed_line"
    assert meta.attributes["country_name"] == "France"
    assert "area" in meta.attributes  # 03 = north-east France


async def test_local_number_needs_a_region():
    _, final, _ = await run_task("0612345678")
    assert final.error.code is ErrorCode.INVALID_INPUT
    assert "default_region" in final.error.message
    _, final, (meta,) = await run_task("0612345678", default_region="fr")
    assert meta.value == "+33612345678"


async def test_invalid_number_is_reported_with_a_message():
    events, final, (meta,) = await run_task("+33 1 23")
    assert final.event is EventKind.COMPLETED
    assert meta.attributes["valid"] is False
    assert any("not a valid number" in (e.message or "") for e in events)


@pytest.mark.parametrize("value", ["+", "+abc"])
async def test_garbage_is_invalid_input(value):
    _, final, _ = await run_task(value)
    assert final.error.code is ErrorCode.INVALID_INPUT
