"""svcs — lightweight DI container (дополняет FastAPI app.state pattern).

svcs vs FastAPI Depends:
- svcs глобальный registry (не привязан к HTTP request)
- FastAPI Depends только в HTTP context
- svcs удобен для background tasks, CLI tools, tests

Usage::

    from app.core.svcs_registry import services, register_factory

    # At startup:
    register_factory(RedisClient, lambda: get_redis_client())
    register_factory(SomeService, SomeService)

    # In code:
    from app.core.svcs_registry import get_service
    redis = get_service(RedisClient)

Fallback: если svcs не установлен, используется простой dict registry.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, TypeVar

__all__ = ("register_factory", "get_service", "services")

logger = logging.getLogger("core.svcs_registry")

T = TypeVar("T")


try:
    import svcs
    SVCS_AVAILABLE = True
    _registry = svcs.Registry()
except ImportError:
    SVCS_AVAILABLE = False
    svcs = None  # type: ignore[assignment]


class _FallbackRegistry:
    """Simple dict-based fallback."""

    def __init__(self) -> None:
        self._factories: dict[type, Callable[[], Any]] = {}
        self._instances: dict[type, Any] = {}

    def register(self, key: type, factory: Callable[[], Any]) -> None:
        self._factories[key] = factory

    def get(self, key: type) -> Any:
        if key in self._instances:
            return self._instances[key]
        factory = self._factories.get(key)
        if factory is None:
            raise KeyError(f"Service not registered: {key.__name__}")
        instance = factory()
        self._instances[key] = instance
        return instance


_fallback = _FallbackRegistry()


def register_factory(key: type, factory: Callable[[], Any]) -> None:
    """Register service factory."""
    if SVCS_AVAILABLE:
        _registry.register_factory(key, factory)
    _fallback.register(key, factory)


def get_service(key: type[T]) -> T:
    """Get service instance."""
    if SVCS_AVAILABLE:
        try:
            container = svcs.Container(_registry)
            return container.get(key)
        except Exception as exc:
            logger.debug("svcs container error, falling back: %s", exc)
    return _fallback.get(key)


services = _fallback  # Alias for direct access
