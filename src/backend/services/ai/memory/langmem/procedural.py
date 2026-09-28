"""Stream E.7: procedural-память LangMem поверх Postgres.

Procedural = "как делать": именованная последовательность шагов
(playbook / SOP / runbook). Хранится в :class:`LangMemProcedural`.
"""

from __future__ import annotations

from typing import Any

__all__ = ("ProceduralMemory",)


class ProceduralMemory:
    """CRUD-операции над процедурной памятью (Postgres)."""

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    async def add(
        self,
        *,
        name: str,
        description: str | None = None,
        steps: dict[str, Any] | None = None,
        tenant: str,
        subject_id: str,
    ) -> int:
        """Сохраняет процедурную запись. Возвращает id.

        Args:
            name: Имя процедуры. Уникально в пределах ТЕНАНТА, а не глобально.
            description: Описание.
            steps: Шаги playbook'а.
            tenant: Тенант-владелец. Обязателен (fail-closed).
            subject_id: Subject-владелец данных (для erasure-контура).

        Raises:
            ValueError: Если ``tenant`` или ``subject_id`` пусты.
        """
        from src.backend.core.domain.models.langmem_models import LangMemProcedural

        if not tenant:
            raise ValueError("tenant обязателен: память без тенанта недопустима")
        if not subject_id:
            raise ValueError("subject_id обязателен: без него erasure невозможен")

        async with self._session_factory() as session:
            row = LangMemProcedural(
                name=name,
                description=description,
                steps=steps,
                tenant=tenant,
                subject_id=subject_id,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return int(row.id)

    async def recall(self, *, tenant: str, limit: int = 20) -> list[dict[str, Any]]:
        """Возвращает последние процедурные записи ТЕНАНТА (updated_at desc).

        ``tenant`` обязателен (ADR-0347): раньше фильтрации не было, и
        ``recall()`` возвращал процедуры всех тенантов сразу.

        Args:
            tenant: Тенант-владелец. Обязателен.
            limit: Максимум возвращаемых записей.

        Returns:
            Список процедур выбранного тенанта.

        Raises:
            ValueError: Если ``tenant`` пуст.
        """
        from src.backend.core.domain.models.langmem_models import LangMemProcedural

        if not tenant:
            raise ValueError(
                "tenant обязателен: чтение памяти другого тенанта недопустимо"
            )

        async with self._session_factory() as session:
            from sqlalchemy import select as sa_select

            stmt = (
                sa_select(LangMemProcedural)
                .where(LangMemProcedural.tenant == tenant)
                .order_by(LangMemProcedural.updated_at.desc())
                .limit(limit)
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [
                {
                    "id": r.id,
                    "name": r.name,
                    "description": r.description,
                    "steps": r.steps,
                }
                for r in rows
            ]
