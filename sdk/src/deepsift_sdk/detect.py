"""Guess the type of a selector typed by a user."""

from __future__ import annotations

import re

from .entities import EntityType

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE = re.compile(r"^\+?[\d\s().-]+$")
_DOMAIN = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}\.?$", re.IGNORECASE
)


def detect_type(selector: str) -> EntityType:
    value = selector.strip()
    if value.lower().startswith(("http://", "https://")):
        return EntityType.URL
    if _EMAIL.match(value):
        return EntityType.EMAIL
    if _PHONE.match(value) and 7 <= sum(ch.isdigit() for ch in value) <= 15:
        return EntityType.PHONE
    if _DOMAIN.match(value):
        return EntityType.DOMAIN
    return EntityType.USERNAME
