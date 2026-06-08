"""Stream E.7: procedural-память LangMem поверх Postgres.

Procedural = "как делать": именованная последовательность шагов
(playbook / SOP / runbook). Хранится в :class:`LangMemProcedural`.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from src.backend.infrastructure.logging.factory import get_logger

logger = get_logger(__name__)

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
        tenant: str | None = None,
    ) -> int:
        """Сохраняет процедурную запись. Возвращает id."""
        from src.backend.services.ai.langmem_models import LangMemProcedural

        async with self._session_factory() as session:
            row = LangMemProcedural(
                name=name, description=description, steps=steps, tenant=tenant
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return int(row.id)

    async def recall(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """Возвращает последние процедурные записи (по updated_at desc)."""
        from src.backend.services.ai.langmem_models import LangMemProcedural

        async with self._session_factory() as session:
            stmt = (
                select(LangMemProcedural)
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
