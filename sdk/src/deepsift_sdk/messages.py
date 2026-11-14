"""Task and event messages carried on the bus (contract sections 5 and 8)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from .entities import Entity, Link
from .ids import new_id

CONTRACT_VERSION = 1


class ErrorCode(StrEnum):
    INVALID_INPUT = "invalid_input"
    NEEDS_CONFIG = "needs_config"
    RATE_LIMITED = "rate_limited"
    UPSTREAM_ERROR = "upstream_error"
    TIMEOUT = "timeout"
    INTERNAL = "internal"


RETRYABLE = frozenset({ErrorCode.RATE_LIMITED, ErrorCode.UPSTREAM_ERROR, ErrorCode.TIMEOUT})


class ErrorInfo(BaseModel):
    code: ErrorCode
    message: str
    retryable: bool

    @classmethod
    def of(cls, code: ErrorCode, message: str, retryable: bool | None = None) -> ErrorInfo:
        return cls(
            code=code,
            message=message,
            retryable=code in RETRYABLE if retryable is None else retryable,
        )


class Task(BaseModel):
    contract: int = CONTRACT_VERSION
    task_id: str = Field(default_factory=new_id)
    run_id: str = Field(default_factory=new_id)
    investigation_id: str | None = None
    service: str
    input: Entity
    options: dict[str, Any] = Field(default_factory=dict)
    deadline: datetime | None = None


class EventKind(StrEnum):
    STARTED = "started"
    PROGRESS = "progress"
    ENTITY = "entity"
    COMPLETED = "completed"
    FAILED = "failed"


class Event(BaseModel):
    contract: int = CONTRACT_VERSION
    task_id: str
    service: str
    event: EventKind
    done: int | None = None
    total: int | None = None
    message: str | None = None
    entity: Entity | None = None
    link: Link | None = None
    count: int | None = None
    error: ErrorInfo | None = None

    @property
    def is_final(self) -> bool:
        return self.event in (EventKind.COMPLETED, EventKind.FAILED)

    def to_json(self) -> str:
        return self.model_dump_json(by_alias=True, exclude_none=True)
