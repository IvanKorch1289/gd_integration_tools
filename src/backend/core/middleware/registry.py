"""MiddlewareRegistry + RouteMiddlewareConfig (S17 K3 W2 scaffold + S70 W1 build_chain).

Контекст:
    Глобальная ASGI-цепочка собирается через
    :class:`entrypoints.middlewares.registry.MiddlewareRegistry` (322 LOC,
    4 layers + per-route gate через ``enabled_routes``/``disabled_routes``).
    Этот модуль добавляет :class:`RouteMiddlewareConfig` — declarative
    per-route override через ``route.toml::[middleware]``.

Sprint 17 (scaffold):
    * :class:`RouteMiddlewareConfig` — frozen-dataclass с ``include``/``exclude``/``overrides``.
    * :meth:`MiddlewareRegistry.register` / :meth:`has` / :meth:`list_registered`.

Sprint 70 W1 (этот commit):
    * :meth:`MiddlewareRegistry.build_chain` — минимальная реализация
      без capability-gate, без audit, без runtime-mount.
      Diff между глобальными defaults и per-route ``include``/``exclude``,
      apply ``overrides`` через partial-apply builder'а.

Wave: ``[wave:s17/k3-w2-middleware-registry]`` + ``[wave:s70/w1-per-route-middleware]``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from functools import reduce
from typing import Any

__all__ = ("MiddlewareRegistry", "RouteMiddlewareConfig")


@dataclass(frozen=True)
class RouteMiddlewareConfig:
    """Декларативное описание per-route middleware chain.

    Поля:
        include: Имена middleware (по ключу регистрации) для включения
            в цепочку для конкретного route. Если пустой — применяются
            глобальные default'ы (все зарегистрированные).
        exclude: Имена middleware для исключения из глобальной цепочки.
        overrides: Per-middleware параметры (``{name: {param: value}}``),
            переопределяющие глобальные настройки.

    Контракт:
        Объект immutable (frozen) — middleware-chain считается за один
        build-step при mount; runtime-mutation запрещена.

    Пример (route.toml)::

        [middleware]
        include = ["rate_limit", "auth", "audit"]
        exclude = ["data_masking"]
        overrides.rate_limit = { limit = 1000, window = "1m" }
    """

    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    overrides: dict[str, dict[str, Any]] = field(default_factory=dict)


class MiddlewareRegistry:
    """Реестр middleware-builder'ов для декларативной композиции chain.

    Контракт:
        * :meth:`register(name, builder)` — сохранить factory.
        * :meth:`build_chain(app, config)` — построить chain для route
          на основе :class:`RouteMiddlewareConfig`.

    Минимальная реализация (S70 W1):
        * Diff между глобальными defaults и ``include``/``exclude``.
        * Apply ``overrides`` через partial-apply builder'а.
        * БЕЗ capability-gate (out of scope: route-level auth policy).
        * БЕЗ runtime-mount (только :class:`FastAPI` ``app.add_middleware``
          в ``setup_middlewares.py``).
        * БЕЗ audit-event (out of scope).
    """

    def __init__(self) -> None:
        self._builders: dict[str, Callable[..., Any]] = {}

    def register(self, name: str, builder: Callable[..., Any]) -> None:
        """Зарегистрировать builder для middleware по имени.

        Args:
            name: Уникальный ключ (используется в ``RouteMiddlewareConfig.include``).
            builder: Factory вида ``(app, **kwargs) -> ASGIApp``.

        Raises:
            ValueError: При повторной регистрации того же имени.
        """
        if name in self._builders:
            raise ValueError(f"Middleware {name!r} уже зарегистрирован")
        self._builders[name] = builder

    def has(self, name: str) -> bool:
        """Проверить, что middleware-builder зарегистрирован."""
        return name in self._builders

    def list_registered(self) -> list[str]:
        """Список всех зарегистрированных middleware (для admin endpoint)."""
        return sorted(self._builders)

    def _resolve_chain_order(self, config: RouteMiddlewareConfig) -> list[str]:
        """Diff между global defaults и per-route include/exclude.

        Returns:
            Имена middleware в порядке применения (outer → inner).

        Raises:
            ValueError: Если ``include`` ссылается на незарегистрированный
                middleware.
        """
        if config.include:
            selected = list(config.include)
            unknown = [name for name in selected if name not in self._builders]
            if unknown:
                raise ValueError(
                    f"Middleware в include не зарегистрированы: {unknown}"
                )
        else:
            selected = self.list_registered()
        return [name for name in selected if name not in config.exclude]

    def build_chain(self, app: Any, config: RouteMiddlewareConfig) -> Any:
        """Построить per-route middleware chain из declarative config.

        Алгоритм:
            1. Diff: вычислить effective middleware list (include ∩ registered) − exclude.
            2. Apply overrides: для каждого middleware передать ``**overrides``
               в builder (partial-apply).
            3. Compose: ``functools.reduce`` по selected (outer → inner).

        Args:
            app: ASGI-приложение / sub-router (то, что оборачиваем).
            config: :class:`RouteMiddlewareConfig` с include/exclude/overrides.

        Returns:
            Wrapped ASGI-приложение с применённой цепочкой middleware.

        Raises:
            ValueError: Если ``include`` ссылается на незарегистрированный
                middleware.

        Example::

            registry = MiddlewareRegistry()
            registry.register("rate_limit", lambda app, **kw: RateLimitMiddleware(app, **kw))
            registry.register("audit", lambda app, **kw: AuditMiddleware(app, **kw))

            config = RouteMiddlewareConfig(
                include=["rate_limit", "audit"],
                overrides={"rate_limit": {"limit": 1000}},
            )
            wrapped = registry.build_chain(app, config)
        """
        selected = self._resolve_chain_order(config)
        if not selected:
            return app

        def wrap(current_app: Any, name: str) -> Any:
            builder = self._builders[name]
            overrides = config.overrides.get(name, {})
            return builder(current_app, **overrides)

        # Outer → inner: первый в selected = самый внешний (Starlette LIFO).
        return reduce(wrap, selected, app)
