"""Database models (SQLAlchemy 2, async). PostgreSQL in the stack, SQLite on a laptop."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from deepsift_sdk.ids import new_id
from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    event,
    inspect,
)
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now() -> datetime:
    return datetime.now(UTC)


def iso(moment: datetime | None) -> str | None:
    """ISO 8601 in UTC. SQLite hands back naive datetimes; they were stored as UTC."""
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.isoformat()


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[str]: JSON, datetime: DateTime(timezone=True)}


class Investigation(Base):
    __tablename__ = "investigations"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(default=now)


class RunStatus:
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), index=True
    )
    selector: Mapped[str] = mapped_column(String(2048))
    type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str] = mapped_column(String(32))
    services: Mapped[list[str]] = mapped_column(default=list)
    options: Mapped[dict[str, Any]] = mapped_column(default=dict)
    max_depth: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default=RunStatus.RUNNING)
    created_at: Mapped[datetime] = mapped_column(default=now)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)


class TaskStatus:
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    FINAL = frozenset({COMPLETED, FAILED, CANCELLED})


class TaskRow(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    service: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(32))
    depth: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default=TaskStatus.QUEUED)
    done: Mapped[int | None] = mapped_column(Integer, default=None)
    total: Mapped[int | None] = mapped_column(Integer, default=None)
    count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    created_at: Mapped[datetime] = mapped_column(default=now)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)


class EntityRow(Base):
    """One entity per identity key and investigation, merged across services."""

    __tablename__ = "entities"
    __table_args__ = (
        UniqueConstraint("investigation_id", "type", "value", name="uq_entity_key"),
        Index("ix_entities_score", "investigation_id", "score"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE")
    )
    type: Mapped[str] = mapped_column(String(32))
    value: Mapped[str] = mapped_column(String(2048))
    attributes: Mapped[dict[str, Any]] = mapped_column(default=dict)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    selector: Mapped[bool] = mapped_column(default=False)
    avatar_group: Mapped[str | None] = mapped_column(String(8), default=None)
    first_seen: Mapped[datetime] = mapped_column(default=now)


class SourceRow(Base):
    """A service that found an entity, with its best confidence."""

    __tablename__ = "sources"

    entity_id: Mapped[str] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True
    )
    service: Mapped[str] = mapped_column(String(64), primary_key=True)
    confidence: Mapped[float] = mapped_column(Float)
    task_id: Mapped[str] = mapped_column(String(26))


class LinkRow(Base):
    __tablename__ = "links"
    __table_args__ = (UniqueConstraint("source_id", "rel", "target_id", name="uq_link"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"))
    rel: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"))


class ServiceSetting(Base):
    """An operator's choice to turn a service on or off, overriding the manifest."""

    __tablename__ = "service_settings"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool]


class SessionRow(Base):
    """Browser sessions. Only the SHA-256 of the cookie value is stored."""

    __tablename__ = "sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=now)
    expires_at: Mapped[datetime]


def make_engine(url: str) -> AsyncEngine:
    engine = create_async_engine(url, pool_pre_ping=not url.startswith("sqlite"))
    if url.startswith("sqlite"):

        @event.listens_for(engine.sync_engine, "connect")
        def _pragmas(connection: Any, _record: Any) -> None:
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)


MIGRATIONS = Path(__file__).parent / "migrations"


def alembic_config(connection: Connection | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


def _upgrade(connection: Connection) -> None:
    config = alembic_config(connection)
    tables = set(inspect(connection).get_table_names())
    if "investigations" in tables and "alembic_version" not in tables:
        # Created by create_all before migrations existed: same schema as the first one.
        command.stamp(config, "0001")
    command.upgrade(config, "head")


async def create_schema(engine: AsyncEngine) -> None:
    """Bring the database to the latest schema (Alembic migrations)."""
    async with engine.begin() as connection:
        await connection.run_sync(_upgrade)
