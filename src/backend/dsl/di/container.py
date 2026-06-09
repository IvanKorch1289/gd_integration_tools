"""Lightweight DI-container для DSL-процессоров.

Резолвит зависимости через три механизма (по приоритету):

1. **Factory** — явно заданная ``InjectMarker.factory``.
2. **Module registry** — ключ ``clients.storage.redis`` →
   ``src.backend.core.di.module_registry.resolve_module``.
3. **App state** — ключ ``reply_registry`` → ``app.state.reply_registry``
   (через ``app_state_singleton``).

Sprint 40 W1.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any, get_type_hints

from src.backend.dsl.di.types import InjectMarker

if TYPE_CHECKING:
    from collections.abc import Callable


class DIError(RuntimeError):
    """Ошибка резолва DI-зависимости."""


class Container:
    """Статический DI-контейнер (singleton resolver)."""

    # Registry маппингов тип → ключ (convention-over-configuration).
    # Пополняется вручную или через auto-discovery.
    _type_map: dict[type[Any], str] = {}

    @staticmethod
    def depends(
        key: str | None = None, *, factory: Callable[..., Any] | None = None
    ) -> InjectMarker:
        """Создать маркер DI-зависимости.

        Примеры::

            # По типу (convention)
            db: DatabaseSessionManager = Container.depends()

            # По явному ключу module_registry
            redis: RedisClient = Container.depends("clients.storage.redis")

            # С factory
            store: MyStore = Container.depends(factory=lambda: MyStore())
        """
        return InjectMarker(key=key, factory=factory)

    @classmethod
    def register_type(cls, type_: type[Any], key: str) -> None:
        """Зарегистрировать маппинг тип → module_registry key."""
        cls._type_map[type_] = key

    @classmethod
    def resolve(cls, marker: InjectMarker, *, hint: type[Any] | None = None) -> Any:
        """Резолвит одну зависимость по маркеру.

        Args:
            marker: ``InjectMarker`` из декоратора/сигнатуры.
            hint: Ожидаемый тип (из ``get_type_hints``).

        Returns:
            Разрешённый инстанс зависимости.

        Raises:
            DIError: Если ни один механизм не смог разрешить зависимость.
        """
        # 1. Factory ( highest priority )
        if marker.factory is not None:
            return marker.factory()

        key = marker.key

        # 2. Explicit key → module_registry or app_state
        if key is not None:
            return cls._resolve_by_key(key)

        # 3. Convention: тип → ключ через _type_map
        if hint is not None:
            mapped = cls._type_map.get(hint)
            if mapped is not None:
                return cls._resolve_by_key(mapped)

            # 4. Fallback: имя типа как ключ module_registry
            type_name = getattr(hint, "__name__", None)
            if type_name:
                return cls._resolve_by_key(type_name, fallback_ok=True)

        raise DIError(
            f"Cannot resolve dependency: marker={marker}, hint={hint}. "
            f"Use Container.depends(key=...) or register_type()."
        )

    @classmethod
    def _resolve_by_key(cls, key: str, *, fallback_ok: bool = False) -> Any:
        """Резолв по ключу: сначала module_registry, потом app_state."""
        # Попытка 1: module_registry (infra-модули)
        try:
            from src.backend.core.di.module_registry import resolve_module

            return resolve_module(key)
        except Exception:
            pass

        # Попытка 2: app.state singleton
        try:
            from src.backend.core.di.app_state import get_app_ref

            app = get_app_ref()
            if app is not None and hasattr(app.state, key):
                return getattr(app.state, key)
        except Exception:
            pass

        if not fallback_ok:
            raise DIError(
                f"Dependency key {key!r} not found in module_registry or app.state"
            )
        raise DIError(
            f"Dependency key {key!r} not found in module_registry or app.state"
        )

    @classmethod
    def resolve_signature(
        cls,
        func: Callable[..., Any],
        *,
        exchange: Any | None = None,
        context: Any | None = None,
    ) -> dict[str, Any]:
        """Резолвит все ``InjectMarker``-параметры функции.

        Args:
            func: Целевая функция / coroutine.
            exchange: Передаётся как ``exchange`` если параметр присутствует.
            context: Передаётся как ``context`` если параметр присутствует.

        Returns:
            Словарь ``{param_name: resolved_value}`` для всех параметров,
            включая injectable и positional (exchange/context).
        """
        sig = inspect.signature(func)
        hints = get_type_hints(func)
        kwargs: dict[str, Any] = {}

        for name, param in sig.parameters.items():
            if name == "exchange" and exchange is not None:
                kwargs[name] = exchange
                continue
            if name == "context" and context is not None:
                kwargs[name] = context
                continue

            default = param.default
            # Проверяем, является ли default InjectMarker
            if (
                hasattr(default, "__class__")
                and default.__class__.__name__ == "InjectMarker"
            ):
                hint = hints.get(name)
                kwargs[name] = cls.resolve(default, hint=hint)  # type: ignore[arg-type]
                continue

            # Обычный параметр с default
            if param.default is not inspect.Parameter.empty:
                kwargs[name] = param.default
                continue

            # Required positional — оставляем на потом (raise if missing)
            kwargs[name] = inspect.Parameter.empty

        return kwargs
