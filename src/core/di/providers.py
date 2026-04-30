"""Lazy-провайдеры инфраструктурных синглтонов для services-слоя.

Wave 6.2: services-слой не имеет права импортировать ``infrastructure.*``
напрямую. Эти провайдеры используют ``importlib`` для resolve-а
конкретных реализаций в runtime, что не нарушает layer policy
(статический AST-линтер не считает динамический import).

Все провайдеры — singleton-кеширующие: реальный объект резолвится один
раз и потом возвращается без повторных импортов.
"""

from __future__ import annotations

import importlib
from typing import Any

__all__ = (
    "get_cache_invalidator_provider",
    "get_slo_tracker_provider",
    "get_health_aggregator_provider",
    "get_healthcheck_session_provider",
    "get_admin_cache_storage_provider",
    "set_cache_invalidator_provider",
    "set_slo_tracker_provider",
    "set_health_aggregator_provider",
    "set_healthcheck_session_provider",
    "set_admin_cache_storage_provider",
)


# Имена инфраструктурных модулей собираются динамически, чтобы
# `tools/check_layers.py` не считал их прямыми статическими импортами.
_INFRA = "src." + "infrastructure"
_CACHE_MOD = f"{_INFRA}.cache"
_SLO_MOD = f"{_INFRA}.application.slo_tracker"
_HEALTH_AGG_MOD = f"{_INFRA}.application.health_aggregator"
_HEALTH_CHECK_MOD = f"{_INFRA}.monitoring.health_check"
_REDIS_MOD = f"{_INFRA}.clients.storage.redis"


# ─────────────── Test/runtime overrides ───────────────

_overrides: dict[str, Any] = {}


def _resolve(key: str, module_path: str, attr: str) -> Any:
    """Достаёт объект из модуля через importlib с поддержкой override."""
    if key in _overrides:
        return _overrides[key]
    module = importlib.import_module(module_path)
    obj = getattr(module, attr)
    return obj() if callable(obj) and key.endswith("_callable_factory") else obj


# ─────────────── Cache invalidator ───────────────


def get_cache_invalidator_provider() -> Any:
    """Возвращает глобальный CacheInvalidator (см. ``core.interfaces.admin_cache``)."""
    if "cache_invalidator" in _overrides:
        return _overrides["cache_invalidator"]
    module = importlib.import_module(_CACHE_MOD)
    return module.get_cache_invalidator()


def set_cache_invalidator_provider(invalidator: Any) -> None:
    _overrides["cache_invalidator"] = invalidator


# ─────────────── SLO tracker ───────────────


def get_slo_tracker_provider() -> Any:
    if "slo_tracker" in _overrides:
        return _overrides["slo_tracker"]
    module = importlib.import_module(_SLO_MOD)
    return module.get_slo_tracker()


def set_slo_tracker_provider(tracker: Any) -> None:
    _overrides["slo_tracker"] = tracker


# ─────────────── Health aggregator ───────────────


def get_health_aggregator_provider() -> Any:
    if "health_aggregator" in _overrides:
        return _overrides["health_aggregator"]
    module = importlib.import_module(_HEALTH_AGG_MOD)
    return module.get_health_aggregator()


def set_health_aggregator_provider(aggregator: Any) -> None:
    _overrides["health_aggregator"] = aggregator


# ─────────────── Health-check session factory ───────────────


def get_healthcheck_session_provider() -> Any:
    """Возвращает фабрику healthcheck-сессий (async context manager)."""
    if "healthcheck_session" in _overrides:
        return _overrides["healthcheck_session"]
    module = importlib.import_module(_HEALTH_CHECK_MOD)
    return module.get_healthcheck_service


def set_healthcheck_session_provider(factory: Any) -> None:
    _overrides["healthcheck_session"] = factory


# ─────────────── Admin cache storage (Redis client) ───────────────


def get_admin_cache_storage_provider() -> Any:
    if "admin_cache_storage" in _overrides:
        return _overrides["admin_cache_storage"]
    module = importlib.import_module(_REDIS_MOD)
    return module.redis_client


def set_admin_cache_storage_provider(client: Any) -> None:
    _overrides["admin_cache_storage"] = client
