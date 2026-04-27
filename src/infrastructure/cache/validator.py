"""
Валидатор конфигурации кэша согласно ADR-004.

Предотвращает двойное кэширование: запрещает включать кэш одновременно
в сервисе и репозитории одной сущности. Двойной кэш приводит к
неконсистентной инвалидации и race conditions (см. ADR-004).

Регистрация:
    Каждый компонент (Service, Repository), участвующий в кэшировании,
    регистрирует свою конфигурацию через ``CacheConfigRegistry.register``.
    Поле ``entity`` идентифицирует целевую сущность, ``layer`` — слой,
    на котором включён кэш (``service`` или ``repository``).

Использование:
    Валидатор вызывается один раз на старте приложения (из lifespan) и
    опционально в ``EntityScaffold`` после генерации нового сервиса.

Пример::

    from src.infrastructure.cache.validator import (
        CacheConfigRegistry, CacheLayerValidator, CacheDuplicationError,
    )

    registry = CacheConfigRegistry()
    registry.register(entity="orders", layer="service", enabled=True)
    registry.register(entity="orders", layer="repository", enabled=True)

    CacheLayerValidator().validate(registry)
    # → CacheDuplicationError: сущность 'orders' имеет кэш на двух уровнях
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

CacheLayer = Literal["service", "repository"]

__all__ = (
    "CacheConfigRegistry",
    "CacheLayerValidator",
    "CacheDuplicationError",
    "CacheConfigEntry",
)


class CacheDuplicationError(Exception):
    """
    Исключение нарушения ADR-004: кэш включён более чем на одном уровне.

    Содержит список сущностей с конфликтующей конфигурацией для диагностики.

    Атрибуты:
        entities: Сущности, у которых кэш активен одновременно на нескольких слоях.
    """

    def __init__(self, entities: list[str]) -> None:
        self.entities = entities
        super().__init__(
            "Обнаружен двойной кэш (ADR-004). Сущности с кэшем на нескольких "
            f"слоях одновременно: {', '.join(sorted(entities))}. "
            "Оставьте кэш только на одном уровне — в Service либо в Repository."
        )


@dataclass(slots=True, frozen=True)
class CacheConfigEntry:
    """
    Одна запись конфигурации кэша для конкретной пары (сущность, слой).

    Атрибуты:
        entity: Логическое имя сущности (``orders``, ``users`` и т.п.).
        layer: Слой ("service" или "repository").
        enabled: Включён ли кэш на этом слое.
    """

    entity: str
    layer: CacheLayer
    enabled: bool


@dataclass(slots=True)
class CacheConfigRegistry:
    """
    In-memory реестр конфигураций кэша проекта.

    Используется ``CacheLayerValidator`` для проверки отсутствия
    двойного кэша. Регистрация идёт на старте приложения — каждый
    сервис и репозиторий сообщает свой ``enabled`` флаг.

    Атрибуты:
        entries: Список зарегистрированных конфигураций.
    """

    entries: list[CacheConfigEntry] = field(default_factory=list)

    def register(self, *, entity: str, layer: CacheLayer, enabled: bool) -> None:
        """
        Добавляет запись о кэше конкретной сущности на конкретном слое.

        Args:
            entity: Имя сущности.
            layer: ``service`` или ``repository``.
            enabled: True, если кэш включён.
        """
        self.entries.append(
            CacheConfigEntry(entity=entity, layer=layer, enabled=enabled)
        )

    def clear(self) -> None:
        """Сбрасывает все записи. Используется в тестах."""
        self.entries.clear()

    def entities_with_cache_on(self, layer: CacheLayer) -> set[str]:
        """Возвращает множество сущностей с включённым кэшем на слое."""
        return {
            entry.entity
            for entry in self.entries
            if entry.layer == layer and entry.enabled
        }


class CacheLayerValidator:
    """
    Валидатор единственного уровня кэша на сущность (ADR-004).

    Проходит по всем зарегистрированным конфигурациям и проверяет,
    что для каждой сущности кэш включён максимум на одном слое.

    Raises:
        CacheDuplicationError: Если обнаружен конфликт кэша.
    """

    def validate(self, registry: CacheConfigRegistry) -> None:
        """
        Проверяет отсутствие конфликтов кэша во всех сущностях реестра.

        Args:
            registry: Реестр конфигураций сервисов и репозиториев.

        Raises:
            CacheDuplicationError: Обнаружен двойной кэш хотя бы у одной сущности.
        """
        service_entities = registry.entities_with_cache_on("service")
        repository_entities = registry.entities_with_cache_on("repository")
        conflicts = service_entities & repository_entities
        if conflicts:
            raise CacheDuplicationError(sorted(conflicts))
