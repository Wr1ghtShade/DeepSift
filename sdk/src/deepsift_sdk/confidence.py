"""Combine confidences from several sources (contract section 13)."""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum

AVATAR_BONUS = 0.15
HIGH = 0.8
MEDIUM = 0.5


class Level(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


def combine(confidences: Iterable[float]) -> float:
    """Noisy-OR: 1 - product of (1 - c). Each extra source raises the score, never past 1."""
    remaining = 1.0
    for confidence in confidences:
        remaining *= 1.0 - _clamp(confidence)
    return round(1.0 - remaining, 4)


def with_avatar_bonus(score: float, linked_avatar: bool) -> float:
    return round(_clamp(score + AVATAR_BONUS), 4) if linked_avatar else score


def level(score: float) -> Level:
    if score >= HIGH:
        return Level.HIGH
    if score >= MEDIUM:
        return Level.MEDIUM
    return Level.LOW
