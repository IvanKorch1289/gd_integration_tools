"""EmbeddingProviderRegistry — параллельный реестр без правки фабрики.

Sprint 1 рефакторит ``services/ai/embedding_providers.py`` целиком; до того
момента BGE-провайдер и любые новые провайдеры регистрируются здесь.
Существующая фабрика ``get_embedding_provider()`` НЕ правится — она
доступна через :meth:`EmbeddingProviderRegistry.fallback_factory`.
"""

from __future__ import annotations

from collections.abc import Callable

from src.backend.core.logging import get_logger
from src.backend.services.ai.embedding_providers import EmbeddingProvider

logger = get_logger(__name__)

__all__ = ("EmbeddingProviderRegistry", "get_embedding_registry")


class EmbeddingProviderRegistry:
    """Реестр именованных embedding-провайдеров (lazy-фабрики)."""

    def __init__(self) -> None:
        self._factories: dict[str, Callable[[], EmbeddingProvider]] = {}
        self._instances: dict[str, EmbeddingProvider] = {}

    def register(self, name: str, factory: Callable[[], EmbeddingProvider]) -> None:
        """Регистрирует фабрику провайдера. Повторная регистрация — overwrite."""
        self._factories[name] = factory
        self._instances.pop(name, None)
        logger.debug("EmbeddingProviderRegistry: registered %r", name)

    def get(self, name: str) -> EmbeddingProvider:
        """Возвращает singleton-инстанс провайдера. Lazy-instantiate."""
        if name in self._instances:
            return self._instances[name]
        if name not in self._factories:
            available = ", ".join(sorted(self._factories.keys())) or "<empty>"
            raise KeyError(
                f"EmbeddingProviderRegistry: provider {name!r} не зарегистрирован. "
                f"Доступные: {available}"
            )
        instance = self._factories[name]()
        self._instances[name] = instance
        return instance

    def list(self) -> list[str]:
        """Возвращает имена зарегистрированных провайдеров."""
        return sorted(self._factories.keys())

    @staticmethod
    def fallback_factory() -> EmbeddingProvider:
        """Делегирует к ``services.ai.embedding_providers.get_embedding_provider``."""
        from src.backend.services.ai.embedding_providers import get_embedding_provider

        return get_embedding_provider()


_singleton: EmbeddingProviderRegistry | None = None


def get_embedding_registry() -> EmbeddingProviderRegistry:
    """Возвращает singleton :class:`EmbeddingProviderRegistry` (process-wide)."""
    global _singleton
    if _singleton is None:
        _singleton = EmbeddingProviderRegistry()
    return _singleton
