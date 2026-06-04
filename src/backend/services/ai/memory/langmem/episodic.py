"""Stream E.7: episodic-память LangMem поверх Postgres.

Episodic = эпизоды диалога / сессии (role + content + meta + timestamp).
Хранится в SQLAlchemy-модели :class:`LangMemEpisodic`.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

logger = logging.getLogger(__name__)

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
        tenant: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> int:
        """Добавляет эпизод. Возвращает id записи."""
        from src.backend.services.ai.langmem_models import LangMemEpisodic

        async with self._session_factory() as session:
            row = LangMemEpisodic(
                session_id=session_id,
                role=role,
                content=content,
                tenant=tenant,
                meta=meta,
                occurred_at=datetime.now(UTC),
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return int(row.id)

    async def recall(
        self, *, session_id: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Возвращает последние эпизоды (опционально фильтр по session_id)."""
        from src.backend.services.ai.langmem_models import LangMemEpisodic

        async with self._session_factory() as session:
            stmt = (
                select(LangMemEpisodic)
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
