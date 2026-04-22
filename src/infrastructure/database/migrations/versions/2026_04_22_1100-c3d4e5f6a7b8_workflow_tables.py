# flake8: noqa
"""add workflow_instances and workflow_events tables + pg_notify trigger

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-22 11:00:00.000000

Создаёт инфраструктуру для durable-workflow engine:

* ``workflow_instances`` — header инстансов (status, version, snapshot,
  advisory lock lease, tenant_id).
* ``workflow_events`` — append-only event log (BIGSERIAL seq, JSONB payload).
* Два PG enum type'а: ``workflow_status``, ``workflow_event_type``.
* Триггер ``trg_workflow_notify`` на INSERT в ``workflow_events`` —
  сигналит воркерам через ``pg_notify('workflow_pending', workflow_id)``
  для типов ``created``/``paused``/``resumed``.

См. также:
    * :mod:`app.infrastructure.database.models.workflow_instance`
    * :mod:`app.infrastructure.database.models.workflow_event`
    * :mod:`app.infrastructure.workflow.event_store`
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


WORKFLOW_STATUS_VALUES = (
    "pending",
    "running",
    "paused",
    "succeeded",
    "failed",
    "cancelling",
    "cancelled",
    "compensating",
)

WORKFLOW_EVENT_TYPE_VALUES = (
    "created",
    "step_started",
    "step_finished",
    "step_failed",
    "branch_taken",
    "loop_iter",
    "sub_spawned",
    "sub_completed",
    "paused",
    "resumed",
    "cancelled",
    "compensated",
    "snapshotted",
)


NOTIFY_FN_SQL = """
CREATE OR REPLACE FUNCTION fn_workflow_notify()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.event_type IN ('created', 'paused', 'resumed') THEN
        PERFORM pg_notify('workflow_pending', NEW.workflow_id::text);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

NOTIFY_TRIGGER_SQL = """
DROP TRIGGER IF EXISTS trg_workflow_notify ON workflow_events;
CREATE TRIGGER trg_workflow_notify
AFTER INSERT ON workflow_events
FOR EACH ROW EXECUTE FUNCTION fn_workflow_notify();
"""


def upgrade() -> None:
    # --- ENUM types -------------------------------------------------------
    workflow_status = postgresql.ENUM(
        *WORKFLOW_STATUS_VALUES, name="workflow_status", create_type=False,
    )
    workflow_event_type = postgresql.ENUM(
        *WORKFLOW_EVENT_TYPE_VALUES, name="workflow_event_type", create_type=False,
    )

    # idempotent create (DROP IF EXISTS на downgrade + CREATE IF NOT EXISTS тут)
    bind = op.get_bind()
    workflow_status.create(bind, checkfirst=True)
    workflow_event_type.create(bind, checkfirst=True)

    # --- workflow_instances ----------------------------------------------
    op.create_table(
        "workflow_instances",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("workflow_name", sa.String(length=256), nullable=False),
        sa.Column("route_id", sa.String(length=256), nullable=False),
        sa.Column(
            "status",
            workflow_status,
            nullable=False,
            server_default=sa.text("'pending'::workflow_status"),
        ),
        sa.Column(
            "current_version",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("last_event_seq", sa.BigInteger(), nullable=True),
        sa.Column("snapshot_state", postgresql.JSONB(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=128), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "tenant_id",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("'default'"),
        ),
        sa.Column(
            "input_payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_instances")),
    )
    op.create_index(
        op.f("ix_workflow_instances_workflow_name"),
        "workflow_instances",
        ["workflow_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workflow_instances_route_id"),
        "workflow_instances",
        ["route_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workflow_instances_status"),
        "workflow_instances",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workflow_instances_next_attempt_at"),
        "workflow_instances",
        ["next_attempt_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workflow_instances_tenant_id"),
        "workflow_instances",
        ["tenant_id"],
        unique=False,
    )

    # --- workflow_events --------------------------------------------------
    op.create_table(
        "workflow_events",
        sa.Column(
            "id", sa.BigInteger(), autoincrement=True, nullable=False,
        ),
        sa.Column(
            "workflow_id", postgresql.UUID(as_uuid=True), nullable=False,
        ),
        sa.Column("event_type", workflow_event_type, nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("step_name", sa.String(length=256), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflow_instances.id"],
            name=op.f("fk_workflow_events_workflow_id_workflow_instances"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_events")),
    )
    op.create_index(
        op.f("ix_workflow_events_workflow_id"),
        "workflow_events",
        ["workflow_id"],
        unique=False,
    )
    op.create_index(
        "ix_workflow_events_workflow_id_seq",
        "workflow_events",
        ["workflow_id", "id"],
        unique=False,
    )

    # --- pg_notify trigger ------------------------------------------------
    op.execute(NOTIFY_FN_SQL)
    op.execute(NOTIFY_TRIGGER_SQL)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_workflow_notify ON workflow_events;")
    op.execute("DROP FUNCTION IF EXISTS fn_workflow_notify();")

    op.drop_index(
        "ix_workflow_events_workflow_id_seq", table_name="workflow_events",
    )
    op.drop_index(
        op.f("ix_workflow_events_workflow_id"), table_name="workflow_events",
    )
    op.drop_table("workflow_events")

    op.drop_index(
        op.f("ix_workflow_instances_tenant_id"), table_name="workflow_instances",
    )
    op.drop_index(
        op.f("ix_workflow_instances_next_attempt_at"),
        table_name="workflow_instances",
    )
    op.drop_index(
        op.f("ix_workflow_instances_status"), table_name="workflow_instances",
    )
    op.drop_index(
        op.f("ix_workflow_instances_route_id"), table_name="workflow_instances",
    )
    op.drop_index(
        op.f("ix_workflow_instances_workflow_name"),
        table_name="workflow_instances",
    )
    op.drop_table("workflow_instances")

    bind = op.get_bind()
    postgresql.ENUM(name="workflow_event_type").drop(bind, checkfirst=True)
    postgresql.ENUM(name="workflow_status").drop(bind, checkfirst=True)
