"""Stream E.7: episodic-память LangMem поверх Postgres.

Episodic = эпизоды диалога / сессии (role + content + meta + timestamp).
Хранится в SQLAlchemy-модели :class:`LangMemEpisodic`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

__all__ = ("EpisodicMemory",)


class EpisodicMemory:
    """CRUD-операции над эпизодической памятью (Postgres)."""

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    async def add(
        self,
        *,
        session_id: str,
        role: str,
        content: str,
        tenant: str,
        subject_id: str,
        meta: dict[str, Any] | None = None,
    ) -> int:
        """Добавляет эпизод. Возвращает id записи.

        Args:
            session_id: Идентификатор сессии диалога.
            role: Роль автора сообщения.
            content: Текст сообщения.
            tenant: Тенант-владелец. Обязателен: fail-closed, пустой тенант
                не должен создавать unscoped-память.
            subject_id: Subject-владелец данных (для erasure-контура).
            meta: Произвольные метаданные.

        Raises:
            ValueError: Если ``tenant`` или ``subject_id`` пусты.
        """
        from src.backend.core.domain.models.langmem_models import LangMemEpisodic

        if not tenant:
            raise ValueError("tenant обязателен: память без тенанта недопустима")
        if not subject_id:
            raise ValueError("subject_id обязателен: без него erasure невозможен")

        async with self._session_factory() as session:
            row = LangMemEpisodic(
                session_id=session_id,
                role=role,
                content=content,
                tenant=tenant,
                subject_id=subject_id,
                meta=meta,
                occurred_at=datetime.now(UTC),
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return int(row.id)

    async def recall(
        self, *, tenant: str, session_id: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Возвращает последние эпизоды ТЕНАНТА (опционально фильтр по session_id).

        ``tenant`` обязателен (ADR-0347). Раньше фильтрации по тенанту не
        было вовсе, поэтому знание/перебор чужого ``session_id`` давало
        чтение памяти другого тенанта — cross-tenant read. Пустой тенант
        теперь приводит к ``ValueError`` (fail-closed), а не к выдаче всех строк.

        Args:
            tenant: Тенант-владелец. Обязателен.
            session_id: Необязательный фильтр по сессии внутри тенанта.
            limit: Максимум возвращаемых записей.

        Returns:
            Список эпизодов выбранного тенанта.

        Raises:
            ValueError: Если ``tenant`` пуст.
        """
        from src.backend.core.domain.models.langmem_models import LangMemEpisodic

        if not tenant:
            raise ValueError(
                "tenant обязателен: чтение памяти другого тенанта недопустимо"
            )

        async with self._session_factory() as session:
            from sqlalchemy import select as sa_select

            stmt = (
                sa_select(LangMemEpisodic)
                .where(LangMemEpisodic.tenant == tenant)
                .order_by(LangMemEpisodic.occurred_at.desc())
                .limit(limit)
            )
            if session_id is not None:
                stmt = stmt.where(LangMemEpisodic.session_id == session_id)
            rows = (await session.execute(stmt)).scalars().all()
            return [
                {
                    "id": r.id,
                    "session_id": r.session_id,
                    "role": r.role,
                    "content": r.content,
                    "meta": r.meta,
                    "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
                }
                for r in rows
            ]
