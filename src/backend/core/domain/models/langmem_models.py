"""SQLAlchemy-модели долговременной памяти LangMem (W2 tenant isolation).

Две сущности:

* :class:`LangMemEpisodic` — события / диалоги (конкретные эпизоды).
* :class:`LangMemProcedural` — выученные процедуры / how-to / playbooks.

Tenant isolation (W2, 2026-09-28)
--------------------------------
Раньше обе таблицы имели только ``session_id``/``name`` + nullable ``tenant``,
и при этом:

* ``LangMemErasureAdapter`` фильтровал по ``subject_id`` — колонки НЕ было
  вовсе, поэтому erasure падал с ``AttributeError`` (см. ADR-0347);
* ``EpisodicMemory.recall()`` фильтровал только по ``session_id``, без tenant,
  то есть знание чужого ``session_id`` давало чтение памяти другого тенанта;
* ``LangMemProcedural.name`` был ``UNIQUE`` глобально — два тенанта не могли
  иметь одноимённую процедуру.

Теперь у обеих таблиц есть ``subject_id`` (для erasure) и обязательная
tenant-семантика на уровне сервисного слоя.
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
    # Subject-владелец данных. NULL допускается только для legacy-строк,
    # созданных до миграции; новые записи обязаны его заполнять.
    subject_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
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
        # Erasure всегда ищет по subject_id (+tenant) — индекс обязателен,
        # иначе DELETE на production-объёме делает full scan.
        Index("ix_langmem_episodic_subject_tenant", "subject_id", "tenant"),
    )


class LangMemProcedural(Base):
    """Процедурный факт (how-to, playbook, rule)."""

    __tablename__ = "langmem_procedural"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    subject_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    tenant: Mapped[str | None] = mapped_column(String(128), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    steps: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("ix_langmem_procedural_tenant", "tenant"),
        Index("ix_langmem_procedural_subject_tenant", "subject_id", "tenant"),
        # Уникальность перенесена с глобальной на пару (name, tenant):
        # глобальный UNIQUE запрещал двум тенантам иметь одноимённую
        # процедуру — это cross-tenant коллизия, а не защита.
        Index("uq_langmem_procedural_name_tenant", "name", "tenant", unique=True),
    )
