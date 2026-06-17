"""LangMem service — long-term memory (episodic / semantic / procedural).

MVP-каркас (Шаг 4). Sprint 4/5 добавит:
* интеграцию с пакетом ``langmem`` (auto-consolidation);
* sync с :class:`AgentMemoryService` (short-term Mongo).

Базовые операции:
* :meth:`add_episodic` — добавить эпизод (роль, контент);
* :meth:`add_procedural` — добавить процедурный факт;
* :meth:`add_semantic` — векторизовать и upsert в Qdrant;
* :meth:`recall` — поиск по типу памяти + опциональный фильтр session_id;
* :meth:`consolidate` — placeholder (Sprint 4).

Default-OFF: при ``LANGMEM_ENABLED=false`` сервис может быть инстанциирован,
но ``add_*`` поднимет :class:`LangMemDisabled`. Это даёт явный сигнал
любому caller'у что память отключена и не пишет данные молчанием.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from src.backend.core.logging import get_logger

logger = get_logger(__name__)

__all__ = ("LangMemDisabled", "LangMemService", "get_langmem_service")


class LangMemDisabled(RuntimeError):
    """Сервис LangMem отключён настройками."""


class LangMemService:
    """Координатор episodic (Postgres) + semantic (Qdrant) + procedural (Postgres)."""

    def __init__(
        self,
        session_factory: Any | None = None,
        qdrant_client: Any | None = None,
        embedder: Any | None = None,
        qdrant_collection: str = "langmem_semantic",
        enabled: bool | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._client = qdrant_client
        self._embedder = embedder
        self._collection = qdrant_collection
        if enabled is None:
            from src.backend.core.config.ai_2026 import langmem_settings

            enabled = langmem_settings.enabled
        self._enabled = bool(enabled)

    def _ensure_enabled(self) -> None:
        if not self._enabled:
            raise LangMemDisabled(
                "LangMem отключён (LANGMEM_ENABLED=false). Включите в config_profiles."
            )

    def _ensure_session_factory(self) -> Any:
        if self._session_factory is not None:
            return self._session_factory
        from src.backend.core.database.initializer import get_db_initializer

        self._session_factory = get_db_initializer().async_session_maker
        return self._session_factory

    async def add_episodic(
        self,
        *,
        session_id: str,
        role: str,
        content: str,
        tenant: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> int:
        """Сохраняет эпизод. Возвращает id записи."""
        self._ensure_enabled()
        from src.backend.services.ai.langmem_models import LangMemEpisodic

        factory = self._ensure_session_factory()
        async with factory() as session:
            row = LangMemEpisodic(
                session_id=session_id,
                role=role,
                content=content,
                tenant=tenant,
                meta=meta,
                occurred_at=datetime.now(timezone.utc),
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return int(row.id)

    async def add_procedural(
        self,
        *,
        name: str,
        description: str | None = None,
        steps: dict[str, Any] | None = None,
        tenant: str | None = None,
    ) -> int:
        self._ensure_enabled()
        from src.backend.services.ai.langmem_models import LangMemProcedural

        factory = self._ensure_session_factory()
        async with factory() as session:
            row = LangMemProcedural(
                name=name, description=description, steps=steps, tenant=tenant
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return int(row.id)

    async def add_semantic(
        self,
        *,
        text: str,
        tenant: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> str:
        """Векторизует ``text`` и upsert в Qdrant. Возвращает point_id."""
        self._ensure_enabled()
        if self._embedder is None or self._client is None:
            raise LangMemDisabled(
                "LangMem.add_semantic: embedder или qdrant_client не сконфигурированы."
            )
        vectors = await self._embedder.embed([text])
        point_id = str(uuid.uuid4())
        payload = {"text": text, **(meta or {})}
        if tenant:
            payload["tenant"] = tenant
        upsert = getattr(self._client, "upsert", None)
        if upsert is not None:
            await upsert(
                collection=self._collection,
                points=[{"id": point_id, "vector": vectors[0], "payload": payload}],
            )
        return point_id

    async def recall(
        self, *, kind: str = "episodic", session_id: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Возвращает последние записи по kind (episodic|procedural)."""
        self._ensure_enabled()
        from src.backend.services.ai.langmem_models import (
            LangMemEpisodic,
            LangMemProcedural,
        )

        factory = self._ensure_session_factory()
        async with factory() as session:
            if kind == "episodic":
                from sqlalchemy import select as sa_select

                stmt = (
                    sa_select(LangMemEpisodic)
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
                        "occurred_at": r.occurred_at.isoformat()
                        if r.occurred_at
                        else None,
                    }
                    for r in rows
                ]
            if kind == "procedural":
                from sqlalchemy import select as sa_select

                stmt = (
                    sa_select(LangMemProcedural)
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
            raise ValueError(f"Неизвестный kind: {kind!r} (episodic|procedural)")

    async def consolidate(
        self, *, since: datetime | None = None, batch_size: int | None = None
    ) -> dict[str, Any]:
        """Wave D.6: episodic → semantic через LLM-summarization.

        Делегирует
        :class:`services.ai.memory.langmem.consolidation.ConsolidationEngine`.
        Возвращает :class:`ConsolidationReport.to_dict()`.
        """
        self._ensure_enabled()
        from src.backend.core.config.ai_2026 import langmem_settings
        from src.backend.services.ai.memory.langmem.consolidation import (
            ConsolidationEngine,
        )

        engine = ConsolidationEngine(langmem_service=self)
        report = await engine.run(
            since=since,
            batch_size=batch_size or langmem_settings.consolidation_batch_size,
        )
        return report.to_dict()

    async def stats(self) -> dict[str, Any]:
        """Wave D.6: общая статистика памяти (counts по типам)."""
        self._ensure_enabled()
        from src.backend.services.ai.langmem_models import (
            LangMemEpisodic,
            LangMemProcedural,
        )

        factory = self._ensure_session_factory()
        async with factory() as session:
            from sqlalchemy import func, select as sa_select

            episodic_count = (
                await session.execute(sa_select(func.count(LangMemEpisodic.id)))
            ).scalar() or 0
            procedural_count = (
                await session.execute(sa_select(func.count(LangMemProcedural.id)))
            ).scalar() or 0
        return {
            "episodic_count": int(episodic_count),
            "procedural_count": int(procedural_count),
        }


_singleton: LangMemService | None = None


def get_langmem_service() -> LangMemService:
    """Возвращает singleton :class:`LangMemService` (process-wide)."""
    global _singleton
    if _singleton is None:
        _singleton = LangMemService()
    return _singleton
