"""Bulkhead registry — singleton container для AdaptiveBulkhead instances.

S174: добавлен как часть ResilienceFacade extension. Хранит именованные
bulkhead'ы и предоставляет lazy-creation через :func:`get_bulkhead_registry`.

Использование::

    from src.backend.core.resilience.bulkhead_registry import get_bulkhead_registry

    registry = get_bulkhead_registry()
    bh = registry.get("kafka_produce") or registry.create(
        "kafka_produce", min_concurrent=2, max_concurrent=20,
    )
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from src.backend.core.logging import get_logger

__all__ = ("BulkheadRegistry", "get_bulkhead_registry")

_logger = get_logger("core.resilience.bulkhead_registry")


class BulkheadRegistry:
    """Реестр именованных :class:`AdaptiveBulkhead` instances."""

    def __init__(self) -> None:
        """Инициализация пустого registry."""
        self._bulkheads: dict[str, Any] = {}

    def get(self, name: str) -> Any | None:
        """Получить bulkhead по имени.

        Args:
            name: Уникальный идентификатор bulkhead'а.

        Returns:
            AdaptiveBulkhead instance или None если не зарегистрирован.
        """
        return self._bulkheads.get(name)

    def register(self, name: str, bulkhead: Any) -> None:
        """Зарегистрировать bulkhead.

        Args:
            name: Уникальный идентификатор.
            bulkhead: AdaptiveBulkhead instance.

        Note:
            Если уже зарегистрирован — перезаписывает (последний wins).
        """
        self._bulkheads[name] = bulkhead
        _logger.info("Bulkhead registered: %s", name)

    def list_names(self) -> list[str]:
        """Список зарегистрированных bulkhead'ов."""
        return list(self._bulkheads.keys())

    def clear(self) -> None:
        """Очистить registry (для тестов)."""
        self._bulkheads.clear()


@lru_cache(maxsize=1)
def get_bulkhead_registry() -> BulkheadRegistry:
    """Lazy singleton глобального :class:`BulkheadRegistry`."""
    return BulkheadRegistry()
