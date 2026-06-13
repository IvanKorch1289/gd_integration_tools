"""S107 W1 — ``core.database.dialect_types``: dialect-aware SQLAlchemy column types.

Helpers для PG-специфичных типов с автоматическим fallback'ом на
портативные аналоги для SQLite. Перемещено из
:mod:`src.backend.infrastructure.database.migrations._compat` (S107 W1,
TD-002 residual) для устранения layer violation: domain models
импортировали ``json_b``/``uuid_t`` из ``infrastructure/``, что
нарушает V22 layer policy.

Использование в моделях::

    from src.backend.core.database.dialect_types import json_b, uuid_t

    class MyModel(BaseModel):
        payload: Mapped[dict] = mapped_column(json_b(), nullable=False)
        id: Mapped[UUID] = mapped_column(uuid_t(), primary_key=True)

Использование в миграциях::

    from src.backend.core.database.dialect_types import json_b, uuid_t

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
