"""Helpers для dialect-aware типов столбцов (W21.2).

Позволяют моделям и миграциям использовать PG-специфичные типы
(JSONB, UUID, ENUM) с автоматическим fallback'ом на портативные
аналоги для SQLite (JSON, String).

Использование в моделях::

    from src.backend.infrastructure.database.migrations._compat import json_b, uuid_t

    class MyModel(BaseModel):
        payload: Mapped[dict] = mapped_column(json_b(), nullable=False)
        id: Mapped[UUID] = mapped_column(uuid_t(), primary_key=True)

Использование в миграциях::

    from src.backend.infrastructure.database.migrations._compat import json_b, uuid_t

    op.create_table("foo", sa.Column("payload", json_b(), nullable=False))
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, String
from sqlalchemy.dialects import postgresql

__all__ = ("json_b", "uuid_t")


def json_b() -> Any:
    """JSONB на PostgreSQL, JSON на остальных диалектах (включая SQLite)."""
    return postgresql.JSONB().with_variant(JSON(), "sqlite")


def uuid_t() -> Any:
    """UUID на PostgreSQL, String(36) на SQLite (хранение в текстовой форме)."""
    return postgresql.UUID(as_uuid=True).with_variant(String(36), "sqlite")
