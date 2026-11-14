"""Entity types and the entity model (contract section 2)."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from .ids import new_id


class EntityType(StrEnum):
    USERNAME = "username"
    EMAIL = "email"
    PHONE = "phone"
    DOMAIN = "domain"
    URL = "url"
    IMAGE = "image"
    PROFILE = "profile"
    ACCOUNT = "account"
    IDENTITY = "identity"
    WEB_PAGE = "web_page"
    PHONE_META = "phone_meta"
    MX_RECORD = "mx_record"
    IMAGE_HASH = "image_hash"
    AVATAR_GROUP = "avatar_group"


#: Types a user can type in as a selector.
SELECTOR_TYPES = frozenset(
    {
        EntityType.USERNAME,
        EntityType.EMAIL,
        EntityType.PHONE,
        EntityType.DOMAIN,
        EntityType.URL,
        EntityType.IMAGE,
    }
)

_PHONE_KEEP = re.compile(r"[^\d+]")
_URL_TYPES = frozenset({EntityType.URL, EntityType.PROFILE, EntityType.WEB_PAGE, EntityType.IMAGE})


def normalize_url(value: str) -> str:
    """Lower-case scheme and host, drop the fragment and a trailing slash.

    The path and the query keep their case: many sites treat them as case-sensitive.
    """
    parts = urlsplit(value)
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return value
    path = parts.path.rstrip("/") if parts.path not in ("", "/") else ""
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def normalize(entity_type: EntityType, value: str) -> str:
    """Return the canonical form of a value, used for the identity key."""
    value = value.strip()
    if entity_type in _URL_TYPES:
        return normalize_url(value)
    match entity_type:
        case EntityType.EMAIL | EntityType.MX_RECORD:
            return value.lower()
        case EntityType.DOMAIN:
            return value.lower().rstrip(".")
        case EntityType.PHONE | EntityType.PHONE_META:
            return _PHONE_KEEP.sub("", value)
        case _:
            return value


class Link(BaseModel):
    """A directed relation from an existing entity to a new one."""

    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(alias="from")
    rel: str


class Entity(BaseModel):
    """A typed piece of data: a selector or something a service found."""

    id: str = Field(default_factory=lambda: "ent_" + new_id())
    type: EntityType
    value: str = Field(min_length=1)
    attributes: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @field_validator("value")
    @classmethod
    def _normalize(cls, value: str, info: ValidationInfo) -> str:
        entity_type = info.data.get("type")
        return normalize(entity_type, value) if entity_type else value.strip()

    @property
    def key(self) -> tuple[str, str]:
        """Identity key: two entities with the same key are the same entity."""
        return (self.type.value, self.value)
