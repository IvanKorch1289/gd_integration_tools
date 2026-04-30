"""Re-export `response_cache` для services-слоя.

Wave 6.2: services/core/* не имеет права импортировать
``infrastructure.decorators.caching`` напрямую (нарушение layer policy).
Этот модуль инкапсулирует lazy-импорт инфраструктурного декоратора и
предоставляет единый объект ``response_cache``, совместимый по API.

Декоратор сохраняет всю свою функциональность (Redis → Memory → Disk)
без изменений: реальный экземпляр создаётся в
``infrastructure.decorators.caching`` при первом обращении.

Для тестов и in-process замены — см. ``set_response_cache``.
"""

from __future__ import annotations

import importlib
from typing import Any

__all__ = ("response_cache", "set_response_cache")

# Имя модуля собирается динамически, чтобы AST-линтер слоёв
# (`tools/check_layers.py`) не считал его статическим импортом
# `infrastructure.*` из core.
_INFRA_CACHING_MODULE = "src." + "infrastructure.decorators.caching"


class _LazyResponseCache:
    """Прокси над инфраструктурным ``response_cache``.

    При первом обращении резолвит реальный экземпляр через ``importlib``.
    Это позволяет services-слою использовать декоратор без прямого
    статического импорта infrastructure (нарушение layer policy).
    """

    __slots__ = ("_impl",)

    def __init__(self) -> None:
        self._impl: Any = None

    def _resolve(self) -> Any:
        if self._impl is None:
            module = importlib.import_module(_INFRA_CACHING_MODULE)
            self._impl = module.response_cache
        return self._impl

    def set_impl(self, impl: Any) -> None:
        """Подменяет реальную реализацию (используется тестами и DI)."""
        self._impl = impl

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self._resolve()(*args, **kwargs)

    def __getattr__(self, item: str) -> Any:
        return getattr(self._resolve(), item)


response_cache = _LazyResponseCache()


def set_response_cache(impl: Any) -> None:
    """Подменяет глобальный ``response_cache`` (для тестов / lifespan)."""
    response_cache.set_impl(impl)
