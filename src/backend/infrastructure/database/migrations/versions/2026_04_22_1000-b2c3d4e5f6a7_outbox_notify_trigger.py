# flake8: noqa
"""outbox NOTIFY trigger — LISTEN/NOTIFY driver для outbox publisher

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-22 10:00:00.000000

IL-CRIT1.4c. Заменяет 5-секундный polling из `OutboxPublisher` на
event-driven pattern:

  INSERT INTO outbox_messages (...)
        │
        ▼  AFTER INSERT trigger
  PERFORM pg_notify('outbox_new', <row_id_as_text>)
        │
        ▼
  `asyncpg` listener (src/infrastructure/eventing/outbox_listener.py)

Снижает нагрузку на БД: 720 req/h простой polling → ~N req/h при N events.

Функция и trigger IDEMPOTENT (CREATE OR REPLACE / DROP IF EXISTS).
Откат миграции: удаляются только trigger и функция, таблица не
затрагивается (она создана в a1b2c3d4e5f6).
"""

from typing import Sequence, Union

from alembic import op


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Функция, которая шлёт NOTIFY с id новой строки в payload-е.
    # Channel 'outbox_new' должен совпадать с CHANNEL в
    # src/infrastructure/eventing/outbox_listener.py.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_outbox_notify()
        RETURNS trigger AS $$
        BEGIN
            -- NEW.id приводится к TEXT; listener читает как UUID строку.
            PERFORM pg_notify('outbox_new', NEW.id::text);
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # 2. Trigger на INSERT; срабатывает PER ROW.
    # Только новые события — update/delete не триггерят NOTIFY.
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_outbox_notify ON outbox_messages;
        CREATE TRIGGER trg_outbox_notify
        AFTER INSERT ON outbox_messages
        FOR EACH ROW
        EXECUTE FUNCTION fn_outbox_notify();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_outbox_notify ON outbox_messages;")
    op.execute("DROP FUNCTION IF EXISTS fn_outbox_notify();")
