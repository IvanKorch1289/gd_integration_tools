"""ServiceDSLRegistry — singleton-реестр сервисов из service.toml.

Хранит зарегистрированные :class:`ServiceSpec` и предоставляет
поиск по имени. Используется DSL-runtime для разрешения сервис-references
в routes (например, ``service:credit_service.calculate_score``).

Default-OFF через ``feature_flags.service_toml_loader``: при выключенном
флаге :meth:`register` молча игнорирует входной spec.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.dsl.service.toml_loader import ServiceSpec

__all__ = ("ServiceDSLRegistry", "get_service_registry")


class ServiceDSLRegistry:
    """Singleton-реестр сервисов из service.toml."""

    def __init__(self) -> None:
        self._services: dict[str, ServiceSpec] = {}

    def register(self, spec: ServiceSpec) -> None:
        """Регистрирует сервис в реестре.

        При default-OFF feature-flag ``service_toml_loader`` — no-op.
        """
        try:
            from src.backend.core.config.features import feature_flags  # noqa: PLC0415

            if not getattr(feature_flags, "service_toml_loader", False):
                return
        except ImportError, AttributeError:
            return

        self._services[spec.name] = spec

    def get(self, name: str) -> ServiceSpec | None:
        """Возвращает зарегистрированный сервис или None."""
        return self._services.get(name)

    def list_all(self) -> list[ServiceSpec]:
        """Возвращает список всех зарегистрированных сервисов."""
        return list(self._services.values())

    def clear(self) -> None:
        """Очищает реестр (используется в тестах)."""
        self._services.clear()


_registry: ServiceDSLRegistry | None = None


def get_service_registry() -> ServiceDSLRegistry:
    """Возвращает singleton ServiceDSLRegistry."""
    global _registry
    if _registry is None:
        _registry = ServiceDSLRegistry()
    return _registry
