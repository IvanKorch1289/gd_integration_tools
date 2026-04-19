"""Re-export для обратной совместимости.

Канонический модуль: ``app.dsl.commands.registry``.
"""

from app.dsl.commands.registry import RouteRegistry, route_registry

__all__ = ("RouteRegistry", "route_registry")
