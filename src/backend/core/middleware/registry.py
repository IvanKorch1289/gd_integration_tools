"""MiddlewareRegistry + RouteMiddlewareConfig scaffold (ADR-A-01).

Контекст:
    Текущая ASGI-цепочка собирается жёстко в
    ``entrypoints/middlewares/setup_middlewares.py``. Per-route override
    невозможен без edit ядра. ADR-A-01 вводит декларативный путь через
    ``route.toml::[middleware]`` + :class:`MiddlewareRegistry`.

Scaffold-only:
    Полная реализация (диспетчеризация, runtime mount, capability-gate,
    overrides resolution) — Sprint 18 K3 W2. В этом scaffold:

    * :class:`RouteMiddlewareConfig` — frozen-dataclass с тремя полями.
    * :class:`MiddlewareRegistry` — заготовка с
      :meth:`register` / :meth:`build_chain` (NotImplementedError).
    * smoke-тест из :mod:`tests.unit.core.middleware.test_registry_stub`
      проверяет публичный контракт без runtime-mount.

Wave: ``[wave:s17/k3-w2-middleware-registry]``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

__all__ = ("MiddlewareRegistry", "RouteMiddlewareConfig")


@dataclass(frozen=True)
class RouteMiddlewareConfig:
    """Декларативное описание per-route middleware chain.

    Поля:
        include: Имена middleware (по ключу регистрации) для включения
            в цепочку для конкретного route. Если пустой — применяются
            глобальные default'ы.
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

    Контракт V22.2 scaffold:
        * :meth:`register(name, builder)` — сохранить factory.
        * :meth:`build_chain(app, config)` — построить chain для route
          (TODO S18: реализация согласно ADR-A-01).

    Полная реализация (Sprint 18 K3 W2) предусматривает:
        * Diff между глобальными default-middleware и
          ``RouteMiddlewareConfig.include``/``exclude``.
        * Применение ``overrides`` через partial-application builder'а.
        * Capability-gate: middleware ``audit``/``rate_limit`` требуют
          declared capability в plugin.toml.
        * Audit-event на построение chain для каждого route.
    """

    def __init__(self) -> None:
        self._builders: dict[str, Callable[..., Any]] = {}

    def register(self, name: str, builder: Callable[..., Any]) -> None:
        """Зарегистрировать builder для middleware по имени.

        Args:
            name: Уникальный ключ (используется в ``RouteMiddlewareConfig``).
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

    def build_chain(self, app: Any, config: RouteMiddlewareConfig) -> Any:
        """Построить per-route middleware chain (TODO S18).

        Сигнатура зафиксирована для будущей реализации. Сейчас
        возвращает ``NotImplementedError`` — scaffold не предназначен
        для runtime-mount.

        Args:
            app: ASGI-приложение / sub-router.
            config: Декларативная конфигурация route.

        Raises:
            NotImplementedError: Полная реализация — Sprint 18 K3 W2.
        """
        del app, config  # сохранены для будущей сигнатуры
        raise NotImplementedError(
            "MiddlewareRegistry.build_chain — scaffold-only (ADR-A-01); "
            "полная реализация запланирована на Sprint 18 K3 W2."
        )
