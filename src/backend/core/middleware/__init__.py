"""Per-route middleware composition (ADR-A-01, S17 K3 W2 + S70 W1).

Назначение:
    Декларативное конфигурирование middleware chain на уровне route.toml
    без переписывания ядра. Заменяет hardcoded ``setup_middlewares.py``
    цепочку статичным registry-разрешением.

Контракт (S70 W1):
    * :class:`RouteMiddlewareConfig` — описание include/exclude/overrides
      из ``route.toml::[middleware]``.
    * :class:`MiddlewareRegistry` — реестр builder'ов middleware с
      :meth:`build_chain` (full implementation per ADR-A-01, S70 W1).
    * :meth:`MiddlewareRegistry.register` / :meth:`has` / :meth:`list_registered`.

S98 W1: Удалён outdated TODO S18 (build_chain уже реализован в S70 W1).
"""

from __future__ import annotations

from src.backend.core.middleware.registry import (
    MiddlewareRegistry,
    RouteMiddlewareConfig,
)

__all__ = ("MiddlewareRegistry", "RouteMiddlewareConfig")
