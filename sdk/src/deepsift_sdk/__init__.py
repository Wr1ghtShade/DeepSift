"""DeepSift service SDK. See docs/specs/service-contract.md."""

from .confidence import Level, combine, level, with_avatar_bonus
from .detect import detect_type
from .entities import SELECTOR_TYPES, Entity, EntityType, Link
from .manifest import Manifest, load_manifest
from .messages import CONTRACT_VERSION, ErrorCode, ErrorInfo, Event, EventKind, Task
from .runner import execute
from .service import Service, ServiceError, TaskContext

__all__ = [
    "CONTRACT_VERSION",
    "SELECTOR_TYPES",
    "Entity",
    "EntityType",
    "ErrorCode",
    "ErrorInfo",
    "Event",
    "EventKind",
    "Level",
    "Link",
    "Manifest",
    "Service",
    "ServiceError",
    "Task",
    "TaskContext",
    "combine",
    "detect_type",
    "execute",
    "level",
    "load_manifest",
    "with_avatar_bonus",
]
