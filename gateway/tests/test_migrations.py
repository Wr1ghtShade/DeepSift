from __future__ import annotations

from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from deepsift_gateway.db import Base, create_schema, make_engine
from sqlalchemy import inspect, text


async def test_migrations_build_the_models_schema(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'm.db'}")
    await create_schema(engine)
    await create_schema(engine)  # idempotent
    async with engine.connect() as connection:

        def check(sync_connection) -> list:
            context = MigrationContext.configure(sync_connection, opts={"compare_type": True})
            return compare_metadata(context, Base.metadata)

        # A model change without a migration fails here: run
        # `alembic revision --autogenerate` through deepsift_gateway.db.alembic_config.
        assert await connection.run_sync(check) == []
        version = await connection.scalar(text("select version_num from alembic_version"))
    assert version == "0001"
    await engine.dispose()


async def test_databases_made_before_migrations_are_adopted(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'old.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await create_schema(engine)
    async with engine.connect() as connection:
        tables = await connection.run_sync(lambda c: inspect(c).get_table_names())
        version = await connection.scalar(text("select version_num from alembic_version"))
    assert "alembic_version" in tables and version == "0001"
    await engine.dispose()
