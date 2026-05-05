"""DI-примитивы уровня core: композиционный корень без infra-зависимостей.

Модуль публикует декоратор-фабрику ``app_state_singleton`` и helper'ы для
доступа к глобальному ``FastAPI``-инстансу из non-request контекстов.

Размещение в core/ позволяет импортировать DI-инструментарий из любого
слоя (services, entrypoints, dsl) без нарушения layer policy.
"""

from src.backend.core.di.app_state import (
    app_state_singleton,
    get_app_ref,
    require_app_ref,
    reset_app_state,
    set_app_ref,
)

__all__ = (
    "app_state_singleton",
    "get_app_ref",
    "require_app_ref",
    "reset_app_state",
    "set_app_ref",
)
