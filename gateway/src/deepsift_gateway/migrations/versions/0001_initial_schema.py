"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-11-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "investigations",
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "service_settings",
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("name"),
    )
    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    op.create_table(
        "entities",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("investigation_id", sa.String(length=26), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("value", sa.String(length=2048), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("selector", sa.Boolean(), nullable=False),
        sa.Column("avatar_group", sa.String(length=8), nullable=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["investigation_id"], ["investigations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("investigation_id", "type", "value", name="uq_entity_key"),
    )
    with op.batch_alter_table("entities", schema=None) as batch_op:
        batch_op.create_index("ix_entities_score", ["investigation_id", "score"], unique=False)

    op.create_table(
        "runs",
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("investigation_id", sa.String(length=26), nullable=False),
        sa.Column("selector", sa.String(length=2048), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.String(length=32), nullable=False),
        sa.Column("services", sa.JSON(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("max_depth", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["investigation_id"], ["investigations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_runs_investigation_id"), ["investigation_id"], unique=False
        )

    op.create_table(
        "links",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("investigation_id", sa.String(length=26), nullable=False),
        sa.Column("source_id", sa.String(length=32), nullable=False),
        sa.Column("rel", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["investigation_id"], ["investigations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_id"], ["entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "rel", "target_id", name="uq_link"),
    )
    with op.batch_alter_table("links", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_links_investigation_id"), ["investigation_id"], unique=False
        )

    op.create_table(
        "sources",
        sa.Column("entity_id", sa.String(length=32), nullable=False),
        sa.Column("service", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("task_id", sa.String(length=26), nullable=False),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("entity_id", "service"),
    )
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("run_id", sa.String(length=26), nullable=False),
        sa.Column("service", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=32), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("done", sa.Integer(), nullable=True),
        sa.Column("total", sa.Integer(), nullable=True),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_tasks_run_id"), ["run_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_tasks_run_id"))

    op.drop_table("tasks")
    op.drop_table("sources")
    with op.batch_alter_table("links", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_links_investigation_id"))

    op.drop_table("links")
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_runs_investigation_id"))

    op.drop_table("runs")
    with op.batch_alter_table("entities", schema=None) as batch_op:
        batch_op.drop_index("ix_entities_score")

    op.drop_table("entities")
    op.drop_table("sessions")
    op.drop_table("service_settings")
    op.drop_table("investigations")
