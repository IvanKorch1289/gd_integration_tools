"""Контракт rule-engine persistence (Wave [wave:s8/k3-rule-engine-finale]).

Domain-модель :class:`RulesetDoc` и :class:`RuleEngineRepository` Protocol —
единственный публичный API для хранения и получения ruleset'ов из БД.
Реализации живут в ``src/backend/infrastructure/repositories/`` и вызываются
через DI (см. ``services/integrations/rule_engine/registry.py``).

Слой: ``core/interfaces/`` — только Protocol + Pydantic. Никаких импортов
SQLAlchemy/драйверов БД (layer-rule из CLAUDE.md V15).
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

__all__ = ("RulesetDoc", "RuleEngineRepository")


class RulesetDoc(BaseModel):
    """Доменная запись ruleset'а в реестре rule-engine.

    Атрибуты:
        id: Опц. PK (None для новой записи перед upsert).
        name: Уникальное имя ruleset'а в рамках ``(name, version, tenant_id)``.
        version: SemVer-подобная версия (произвольная строка; уникальна вместе с
            ``name`` + ``tenant_id``).
        yaml_body: Сырое YAML-тело ruleset'а (см.
            ``docs/dsl/rule-engine-example.yaml``).
        enabled: Если ``False`` — реестр игнорирует запись при ``list_active``.
        tenant_id: Опц. tenant scope; ``None`` означает глобальный ruleset.
        created_at: Время создания (UTC).
        updated_at: Время последнего изменения (UTC).
    """

    model_config = ConfigDict(frozen=False, from_attributes=True)

    id: int | None = Field(default=None)
    name: str
    version: str = Field(default="1")
    yaml_body: str
    enabled: bool = Field(default=True)
    tenant_id: str | None = Field(default=None)
    created_at: datetime | None = Field(default=None)
    updated_at: datetime | None = Field(default=None)


@runtime_checkable
class RuleEngineRepository(Protocol):
    """Контракт хранилища ruleset'ов rule-engine.

    Реализация — :class:`SQLRuleEngineRepository` в
    ``src/backend/infrastructure/repositories/rule_engine_repository.py``.
    Для unit-тестов registry используется in-memory fake.
    """

    async def get(
        self, name: str, *, version: str | None = None, tenant_id: str | None = None
    ) -> RulesetDoc | None:
        """Вернуть последнюю включённую запись по ``(name, version?, tenant?)``.

        Если ``version`` не задана — возвращается запись с максимальной
        ``version`` (лексикографически).
        """
        ...

    async def list_active(self, *, tenant_id: str | None = None) -> list[RulesetDoc]:
        """Список всех ``enabled=True`` записей; опц. фильтр по tenant'у."""
        ...

    async def upsert(self, doc: RulesetDoc) -> RulesetDoc:
        """Создать или обновить запись по ``(name, version, tenant_id)``.

        Возвращает запись с проставленным ``id`` / ``created_at`` /
        ``updated_at``.
        """
        ...

    async def delete(
        self, name: str, version: str, *, tenant_id: str | None = None
    ) -> bool:
        """Удалить запись по составному ключу. Возвращает ``True`` при успехе."""
        ...
