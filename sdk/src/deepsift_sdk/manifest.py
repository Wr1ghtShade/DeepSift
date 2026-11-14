"""Service manifest (contract section 3)."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from .entities import EntityType
from .messages import CONTRACT_VERSION

_DURATION = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(ms|s|m|h)?\s*$")
_UNITS = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0, None: 1.0}
_RATE = re.compile(r"^\s*(\d+)\s*/\s*(s|m|h)\s*$")


def parse_duration(value: Any) -> float:
    """Parse '300s', '5m', '1.5h', '250ms' or a number of seconds."""
    if isinstance(value, int | float):
        return float(value)
    match = _DURATION.match(str(value))
    if not match:
        raise ValueError(f"invalid duration: {value!r}")
    return float(match.group(1)) * _UNITS[match.group(2)]


class OptionSpec(BaseModel):
    type: Literal["enum", "int", "bool", "str"]
    values: list[Any] | None = None
    default: Any = None
    description: str = ""


class Manifest(BaseModel):
    contract: int = CONTRACT_VERSION
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    version: str
    description: str = ""
    inputs: list[EntityType] = Field(min_length=1)
    outputs: list[EntityType] = Field(min_length=1)
    links: list[str] = Field(default_factory=list)
    mode: Literal["library", "api", "local"]
    license: str
    timeout: float = 60.0
    concurrency: int = Field(default=1, ge=1)
    rate_limit: str | None = None
    secrets: list[str] = Field(default_factory=list)
    config: list[str] = Field(default_factory=list)
    optional_secrets: list[str] = Field(default_factory=list)
    enabled_by_default: bool = True
    options: dict[str, OptionSpec] = Field(default_factory=dict)

    @field_validator("timeout", mode="before")
    @classmethod
    def _timeout(cls, value: Any) -> float:
        return parse_duration(value)

    @field_validator("rate_limit")
    @classmethod
    def _rate(cls, value: str | None) -> str | None:
        if value is not None and not _RATE.match(value):
            raise ValueError(f"invalid rate limit: {value!r} (expected e.g. '1/s')")
        return value

    def accepts(self, entity_type: EntityType) -> bool:
        return entity_type in self.inputs

    def missing_secrets(self, env: Mapping[str, str] | None = None) -> list[str]:
        """Required environment variables that are not set: secrets, then config."""
        env = os.environ if env is None else env
        return [name for name in (*self.secrets, *self.config) if not env.get(name)]

    def missing_optional_secrets(self, env: Mapping[str, str] | None = None) -> list[str]:
        env = os.environ if env is None else env
        return [name for name in self.optional_secrets if not env.get(name)]

    def option_default(self, name: str) -> Any:
        spec = self.options.get(name)
        return spec.default if spec else None


def load_manifest(path: str | Path) -> Manifest:
    with open(path, encoding="utf-8") as handle:
        return Manifest.model_validate(yaml.safe_load(handle))
