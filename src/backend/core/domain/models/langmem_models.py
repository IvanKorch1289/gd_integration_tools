"""ORM-модели LangMem (К4 MVP, Шаг 4).

Три типа long-term memory:

* :class:`LangMemEpisodic` — события / диалоги (конкретные эпизоды).
* :class:`LangMemProcedural` — выученные процедуры / how-to / playbooks.
* Semantic-факты живут в Qdrant (по collection ``langmem_semantic``)
  — отдельной ORM-таблицы для них нет.

Таблицы создаются миграцией Alembic
``a8b9c0d1e2f3_add_langmem_tables.py``. Default-OFF: при
``LANGMEM_ENABLED=false`` миграция всё равно создаёт пустые таблицы
(идемпотентно).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

__all__ = ("LangMemEpisodic", "LangMemProcedural")


class LangMemEpisodic(Base):
    """Эпизод (диалог / событие) с временной привязкой."""

    __tablename__ = "langmem_episodic"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(128), nullable=False)
    tenant: Mapped[str | None] = mapped_column(String(128), nullable=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_langmem_episodic_session_time", "session_id", "occurred_at"),
        Index("ix_langmem_episodic_tenant", "tenant"),
    )


class LangMemProcedural(Base):
    """Процедурный факт (how-to, playbook, rule)."""

    __tablename__ = "langmem_procedural"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    tenant: Mapped[str | None] = mapped_column(String(128), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    steps: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (Index("ix_langmem_procedural_tenant", "tenant"),)
