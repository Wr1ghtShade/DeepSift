"""Sortable unique identifiers (ULID format, Crockford base32)."""

from __future__ import annotations

import os
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_id() -> str:
    """Return a new 26-character ULID: 48 bits of milliseconds then 80 random bits."""
    value = (int(time.time() * 1000) << 80) | int.from_bytes(os.urandom(10), "big")
    return "".join(_ALPHABET[(value >> (5 * i)) & 31] for i in reversed(range(26)))
