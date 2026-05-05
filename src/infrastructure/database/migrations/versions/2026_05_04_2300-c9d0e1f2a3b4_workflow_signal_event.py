# flake8: noqa
"""add 'signal_received' value to workflow_event_type enum (Wave D.1).

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-05-04 23:00:00.000000

Wave D.1 / ADR-045: добавляет тип события ``signal_received`` для
``PgRunnerWorkflowBackend`` adapter'а, эмулирующего
``WorkflowBackend.signal_workflow`` через append в event-log.

Postgres ``ALTER TYPE ... ADD VALUE`` нельзя откатить
(``DROP VALUE`` не поддерживается); downgrade логически no-op.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "ALTER TYPE workflow_event_type ADD VALUE IF NOT EXISTS 'signal_received'"
        )
    # SQLite/иные диалекты — enum хранится как string, расширение не требуется.


def downgrade() -> None:
    # PostgreSQL не поддерживает DROP VALUE для enum-типов;
    # downgrade сознательно no-op (значение остаётся допустимым).
    pass
