"""SQLAlchemy 2.x async-репозиторий ruleset'ов rule-engine.

Wave: ``[wave:s8/k3-rule-engine-finale]``. Реализация Protocol
:class:`src.backend.core.interfaces.rule_engine.RuleEngineRepository`
поверх таблицы ``rule_engine_rulesets`` (см. ORM-модель
:class:`src.backend.infrastructure.database.models.rule_engine.RuleEngineRulesetORM`
и Alembic-миграцию ``e1f2a3b4c5d6``).

Используется через :class:`RuleEngineRegistry`
(``src/backend/services/integrations/rule_engine/registry.py``):
сам репозиторий не кэширует — кэш живёт в registry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete, select

from src.backend.core.interfaces.rule_engine import RuleEngineRepository, RulesetDoc
from src.backend.core.domain.models.rule_engine import RuleEngineRulesetORM

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ("SQLRuleEngineRepository",)


class SQLRuleEngineRepository(RuleEngineRepository):
    """Async SQLAlchemy-репозиторий ruleset'ов rule-engine.

    Args:
        session: Активная :class:`AsyncSession`. Транзакционность —
            ответственность вызывающего (registry открывает сессию
            на каждый запрос; commit на upsert/delete).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_doc(orm: RuleEngineRulesetORM) -> RulesetDoc:
        """Преобразует ORM-сущность в доменную :class:`RulesetDoc`.

        Используется явная распаковка вместо ``model_validate(orm)`` —
        async ORM-атрибуты, заполненные через ``server_default`` после
        flush, могут потребовать ``await refresh()`` для materialization;
        repo вызывает :meth:`AsyncSession.refresh` явно перед маппингом.
        """
        return RulesetDoc(
            id=orm.id,
            name=orm.name,
            version=orm.version,
            yaml_body=orm.yaml_body,
            enabled=orm.enabled,
            tenant_id=orm.tenant_id,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    async def get(
        self, name: str, *, version: str | None = None, tenant_id: str | None = None
    ) -> RulesetDoc | None:
        """Вернуть включённый ruleset по имени.

        Если ``version`` не задана — берётся запись с максимальной
        ``version`` (лексикографическая сортировка по убыванию).
        """
        stmt = select(RuleEngineRulesetORM).where(
            RuleEngineRulesetORM.name == name, RuleEngineRulesetORM.enabled.is_(True)
        )
        if tenant_id is None:
            stmt = stmt.where(RuleEngineRulesetORM.tenant_id.is_(None))
        else:
            stmt = stmt.where(RuleEngineRulesetORM.tenant_id == tenant_id)
        if version is not None:
            stmt = stmt.where(RuleEngineRulesetORM.version == version)
        else:
            stmt = stmt.order_by(RuleEngineRulesetORM.version.desc())

        stmt = stmt.limit(1)
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        return self._to_doc(orm) if orm is not None else None

    async def list_active(self, *, tenant_id: str | None = None) -> list[RulesetDoc]:
        """Список всех включённых ruleset'ов; опц. фильтр по tenant'у."""
        stmt = select(RuleEngineRulesetORM).where(
            RuleEngineRulesetORM.enabled.is_(True)
        )
        if tenant_id is not None:
            stmt = stmt.where(RuleEngineRulesetORM.tenant_id == tenant_id)
        stmt = stmt.order_by(
            RuleEngineRulesetORM.name, RuleEngineRulesetORM.version.desc()
        )
        result = await self._session.execute(stmt)
        return [self._to_doc(orm) for orm in result.scalars().all()]

    async def upsert(self, doc: RulesetDoc) -> RulesetDoc:
        """Создать или обновить запись по ``(name, version, tenant_id)``."""
        # Поиск существующей записи через составной ключ.
        stmt = select(RuleEngineRulesetORM).where(
            RuleEngineRulesetORM.name == doc.name,
            RuleEngineRulesetORM.version == doc.version,
        )
        if doc.tenant_id is None:
            stmt = stmt.where(RuleEngineRulesetORM.tenant_id.is_(None))
        else:
            stmt = stmt.where(RuleEngineRulesetORM.tenant_id == doc.tenant_id)

        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            orm = RuleEngineRulesetORM(
                name=doc.name,
                version=doc.version,
                yaml_body=doc.yaml_body,
                enabled=doc.enabled,
                tenant_id=doc.tenant_id,
            )
            self._session.add(orm)
        else:
            orm.yaml_body = doc.yaml_body
            orm.enabled = doc.enabled

        await self._session.flush()
        await self._session.refresh(orm)
        return self._to_doc(orm)

    async def delete(
        self, name: str, version: str, *, tenant_id: str | None = None
    ) -> bool:
        """Удалить запись по составному ключу."""
        stmt = delete(RuleEngineRulesetORM).where(
            RuleEngineRulesetORM.name == name, RuleEngineRulesetORM.version == version
        )
        if tenant_id is None:
            stmt = stmt.where(RuleEngineRulesetORM.tenant_id.is_(None))
        else:
            stmt = stmt.where(RuleEngineRulesetORM.tenant_id == tenant_id)
        result = await self._session.execute(stmt)
        return (result.rowcount or 0) > 0  # type: ignore[attr-defined]
