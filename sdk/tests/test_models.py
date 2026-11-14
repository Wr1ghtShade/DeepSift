from __future__ import annotations

import pytest
from deepsift_sdk import Entity, EntityType, Event, EventKind, Link, combine, detect_type, level
from deepsift_sdk.confidence import Level, with_avatar_bonus
from deepsift_sdk.ids import new_id
from deepsift_sdk.manifest import load_manifest, parse_duration
from pydantic import ValidationError


def test_new_id_is_ulid_and_sortable():
    first, second = new_id(), new_id()
    assert len(first) == 26
    assert first[:10] <= second[:10]


@pytest.mark.parametrize(
    ("entity_type", "raw", "expected"),
    [
        (EntityType.EMAIL, "  John.Doe@Example.ORG ", "john.doe@example.org"),
        (EntityType.DOMAIN, "Example.ORG.", "example.org"),
        (EntityType.PHONE, "+33 6 12-34.56(78)", "+33612345678"),
        (EntityType.USERNAME, " NightOwl ", "NightOwl"),
        (EntityType.PROFILE, "HTTPS://GitHub.com/NightOwl/", "https://github.com/NightOwl"),
        (EntityType.PROFILE, "https://x.example/u?id=7#top", "https://x.example/u?id=7"),
        (EntityType.URL, "https://example.org/", "https://example.org"),
        (EntityType.IMAGE, "blob:abc123", "blob:abc123"),
    ],
)
def test_entity_values_are_normalized(entity_type, raw, expected):
    assert Entity(type=entity_type, value=raw).value == expected


def test_entities_with_same_key_are_the_same():
    a = Entity(type=EntityType.EMAIL, value="A@b.org")
    b = Entity(type=EntityType.EMAIL, value="a@B.org")
    assert a.id != b.id
    assert a.key == b.key


def test_entity_confidence_is_bounded():
    with pytest.raises(ValidationError):
        Entity(type=EntityType.USERNAME, value="x", confidence=1.5)


def test_event_json_uses_contract_field_names():
    event = Event(
        task_id="t",
        service="s",
        event=EventKind.ENTITY,
        entity=Entity(type=EntityType.PROFILE, value="https://x"),
        link=Link(from_="ent_1", rel="found_on"),
    )
    data = event.to_json()
    assert '"from":"ent_1"' in data
    assert "error" not in data
    assert Event.model_validate_json(data).link.from_ == "ent_1"


@pytest.mark.parametrize(
    ("value", "seconds"), [("300s", 300), ("5m", 300), ("250ms", 0.25), (12, 12), ("1.5h", 5400)]
)
def test_parse_duration(value, seconds):
    assert parse_duration(value) == seconds


def test_load_manifest(tmp_path):
    path = tmp_path / "manifest.yaml"
    path.write_text(
        "contract: 1\nname: demo\nversion: 1.0.0\ninputs: [username]\noutputs: [profile]\n"
        "mode: library\nlicense: MIT\ntimeout: 2m\nrate_limit: 1/s\nsecrets: [DEMO_KEY]\n"
        "options:\n  depth:\n    type: enum\n    values: [a, b]\n    default: a\n"
    )
    manifest = load_manifest(path)
    assert manifest.timeout == 120
    assert manifest.accepts(EntityType.USERNAME)
    assert not manifest.accepts(EntityType.EMAIL)
    assert manifest.option_default("depth") == "a"
    assert manifest.missing_secrets({}) == ["DEMO_KEY"]
    assert manifest.missing_secrets({"DEMO_KEY": "x"}) == []
    assert manifest.optional_secrets == []


def test_manifest_rejects_bad_name_and_rate(tmp_path):
    from deepsift_sdk import Manifest

    base = {
        "version": "1",
        "inputs": ["username"],
        "outputs": ["profile"],
        "mode": "local",
        "license": "MIT",
    }
    with pytest.raises(ValidationError):
        Manifest.model_validate({**base, "name": "Bad Name"})
    with pytest.raises(ValidationError):
        Manifest.model_validate({**base, "name": "ok", "rate_limit": "fast"})


def test_noisy_or_matches_spec_example():
    assert combine([0.6, 0.7]) == 0.88
    assert combine([0.6]) == 0.6
    assert combine([]) == 0.0
    assert combine([1.0, 0.2]) == 1.0


def test_levels_and_avatar_bonus():
    assert level(0.88) is Level.HIGH
    assert level(0.6) is Level.MEDIUM
    assert level(0.49) is Level.LOW
    assert with_avatar_bonus(0.6, True) == 0.75
    assert with_avatar_bonus(0.95, True) == 1.0
    assert with_avatar_bonus(0.6, False) == 0.6


@pytest.mark.parametrize(
    ("selector", "expected"),
    [
        ("nightowl_77", EntityType.USERNAME),
        ("john@example.org", EntityType.EMAIL),
        ("+33 6 12 34 56 78", EntityType.PHONE),
        ("0612345678", EntityType.PHONE),
        ("example-shop.fr", EntityType.DOMAIN),
        ("https://github.com/x", EntityType.URL),
        ("john_doe", EntityType.USERNAME),
        # Ambiguous: "john.doe" looks like a domain. Use `deepsift user` to force the type.
        ("john.doe", EntityType.DOMAIN),
        ("1234", EntityType.USERNAME),
    ],
)
def test_detect_type(selector, expected):
    assert detect_type(selector) is expected
