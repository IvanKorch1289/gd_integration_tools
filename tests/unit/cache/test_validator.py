"""
Тесты CacheLayerValidator (ADR-004).

Проверяют:
    * Валидная конфигурация (кэш только в Service) — проходит.
    * Валидная конфигурация (кэш только в Repository) — проходит.
    * Конфигурация без кэша на обоих слоях — проходит.
    * Двойной кэш (Service + Repository у одной сущности) → CacheDuplicationError.
    * Множественные конфликты агрегируются в сообщение ошибки.
"""

from __future__ import annotations

import pytest

from src.infrastructure.cache.validator import (
    CacheConfigRegistry,
    CacheDuplicationError,
    CacheLayerValidator,
)


def test_service_only_cache_is_valid() -> None:
    """Кэш только в Service → проверка проходит без ошибок."""
    registry = CacheConfigRegistry()
    registry.register(entity="orders", layer="service", enabled=True)
    registry.register(entity="orders", layer="repository", enabled=False)

    CacheLayerValidator().validate(registry)


def test_repository_only_cache_is_valid() -> None:
    """Кэш только в Repository → проверка проходит без ошибок."""
    registry = CacheConfigRegistry()
    registry.register(entity="users", layer="service", enabled=False)
    registry.register(entity="users", layer="repository", enabled=True)

    CacheLayerValidator().validate(registry)


def test_no_cache_at_all_is_valid() -> None:
    """Сущность без кэша — допустимо."""
    registry = CacheConfigRegistry()
    registry.register(entity="files", layer="service", enabled=False)
    registry.register(entity="files", layer="repository", enabled=False)

    CacheLayerValidator().validate(registry)


def test_duplicate_cache_raises() -> None:
    """Двойной кэш у одной сущности → CacheDuplicationError."""
    registry = CacheConfigRegistry()
    registry.register(entity="orders", layer="service", enabled=True)
    registry.register(entity="orders", layer="repository", enabled=True)

    with pytest.raises(CacheDuplicationError) as excinfo:
        CacheLayerValidator().validate(registry)

    assert "orders" in excinfo.value.entities


def test_multiple_conflicts_are_reported() -> None:
    """Несколько сущностей с двойным кэшем → все в сообщении ошибки."""
    registry = CacheConfigRegistry()
    for entity in ("orders", "users", "files"):
        registry.register(entity=entity, layer="service", enabled=True)
        registry.register(entity=entity, layer="repository", enabled=True)

    with pytest.raises(CacheDuplicationError) as excinfo:
        CacheLayerValidator().validate(registry)

    assert set(excinfo.value.entities) == {"orders", "users", "files"}


def test_empty_registry_is_valid() -> None:
    """Пустой реестр (ничего не зарегистрировано) → проверка проходит."""
    CacheLayerValidator().validate(CacheConfigRegistry())
