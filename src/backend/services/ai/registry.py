"""Sprint 14 K4 W1 — реестр AI-сервисов плагинов.

Назначение:
    Singleton, в котором ``@ai_service`` декораторы сохраняют свои
    :class:`AIServiceSpec`. Используется:

    * admin-эндпоинтом ``/api/v1/admin/ai/services`` для каталога;
    * AI Cost Dashboard для учёта model usage;
    * MCP-сервером (FastMCP) для exposure tools.

Принципы:
    - Идемпотентная регистрация: повторный вызов с тем же ``name`` не
      пугает — просто перезаписывает spec (актуально для hot-reload);
    - Thread-safe не требуется — registry заполняется при import-time
      плагинов, обращения только из event-loop.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.services.ai.decorators import AIServiceSpec

__all__ = (
    "AIPluginRegistry",
    "get_ai_plugin_registry",
)

_logger = logging.getLogger("services.ai.registry")


class AIPluginRegistry:
    """In-process реестр зарегистрированных AI-сервисов."""

    def __init__(self) -> None:
        self._specs: dict[str, AIServiceSpec] = {}

    def register(self, spec: "AIServiceSpec") -> None:
        """Зарегистрировать новый spec (overwrite by name)."""
        if spec.name in self._specs:
            _logger.debug("AI service overwrite: %s", spec.name)
        self._specs[spec.name] = spec

    def get(self, name: str) -> "AIServiceSpec | None":
        """Получить spec по имени, ``None`` если не найден."""
        return self._specs.get(name)

    def all(self) -> list["AIServiceSpec"]:
        """Все зарегистрированные сервисы (sorted by name)."""
        return [self._specs[n] for n in sorted(self._specs)]

    def clear(self) -> None:
        """Сбросить реестр (для тестов и hot-swap)."""
        self._specs.clear()


_REGISTRY = AIPluginRegistry()


def get_ai_plugin_registry() -> AIPluginRegistry:
    """Singleton accessor."""
    return _REGISTRY
