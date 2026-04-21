"""DEPRECATION SHIM — ``service_registry`` заменён на ``svcs_registry``.

Этот модуль оставлен на один релиз (удаление запланировано на 2026-07-01,
см. ``docs/DEPRECATIONS.md``). Все обращения к ``service_registry`` и
``ServiceRegistry`` проксируются в ``app.core.svcs_registry``.

Импорты выдают ``DeprecationWarning``; после 2026-07-01 модуль будет
удалён безусловно — рекомендуется обновить импорты сейчас.
"""

from __future__ import annotations

import warnings
from typing import Any, Callable

from app.core.svcs_registry import (
    clear_registry as _clear,
    get_service,
    has_service,
    list_services as _list_services,
    register_factory,
)

__all__ = ("ServiceRegistry", "service_registry")

warnings.warn(
    "`app.core.service_registry` deprecated (ADR-002). "
    "Используйте `app.core.svcs_registry.{register_factory,get_service}`. "
    "Модуль будет удалён 2026-07-01.",
    DeprecationWarning,
    stacklevel=2,
)


class ServiceRegistry:
    """Shim над svcs_registry для старого name-based API.

    Новый код должен использовать ``from app.core.svcs_registry import
    register_factory, get_service`` напрямую.
    """

    @staticmethod
    def register(name: str, factory: Callable[[], Any]) -> None:
        register_factory(name, factory)

    @staticmethod
    def get(name: str) -> Any:
        return get_service(name)

    @staticmethod
    def list_services() -> list[str]:
        return _list_services()

    @staticmethod
    def is_registered(name: str) -> bool:
        return has_service(name)

    @staticmethod
    def clear() -> None:
        _clear()


service_registry = ServiceRegistry()
