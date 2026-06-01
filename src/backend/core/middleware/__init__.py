"""Per-route middleware composition (ADR-A-01, Sprint 17 K3 W2 scaffold).

Назначение:
    Декларативное конфигурирование middleware chain на уровне route.toml
    без переписывания ядра. Заменяет hardcoded ``setup_middlewares.py``
    цепочку статичным registry-разрешением.

Контракт V22.2 (scaffold-only):
    * :class:`RouteMiddlewareConfig` — описание include/exclude/overrides
      из ``route.toml::[middleware]``.
    * :class:`MiddlewareRegistry` — реестр builder'ов middleware с
      :meth:`build_chain` (TODO S18: full implementation per ADR-A-01).

Полная реализация — Sprint 18 K3 W2 (carryover).
"""

from __future__ import annotations

from src.backend.core.middleware.registry import (
    MiddlewareRegistry,
    RouteMiddlewareConfig,
)

__all__ = ("MiddlewareRegistry", "RouteMiddlewareConfig")
