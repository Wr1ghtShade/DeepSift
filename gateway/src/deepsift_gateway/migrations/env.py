"""Alembic environment. The gateway runs migrations itself at start (db.migrate), on
the connection it hands over in ``config.attributes["connection"]``."""

from __future__ import annotations

from alembic import context
from deepsift_gateway.db import Base

config = context.config
target_metadata = Base.metadata


def run(connection) -> None:  # type: ignore[no-untyped-def]
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=connection.dialect.name == "sqlite",
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


connection = config.attributes.get("connection")
if connection is None:
    raise RuntimeError("run migrations through deepsift_gateway.db.migrate()")
run(connection)
