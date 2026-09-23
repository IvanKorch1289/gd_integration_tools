"""Resilience providers — coordinator, components_report, rate_limiter (W9 P2-13 Phase 7).

W9 P2-13 Phase 7 (cycle 153): извлечено из ``core/di/providers/workflow.py``
(602 LOC god-module). Содержит ResilienceCoordinator + components_report +
rate_limiter/classes.

Back-compat: ``core/di/providers/workflow.py`` (file) продолжает re-export
все 5 funcs через thin ``__init__.py`` shim (см. ADR-0331).

Singleton cache ``_overrides`` is per-domain (NOT shared).
"""

from __future__ import annotations

from typing import Any

from src.backend.core.di.module_registry import resolve_module
from src.backend.core.di.providers.workflow._overrides_store import register

_overrides: dict[str, Any] = {}
register(_overrides)  # aggregate back-compat (providers.workflow._overrides)


# ─────────────── Resilience coordinator / health report ───────────────


def get_resilience_coordinator_provider() -> Any:
    """Возвращает singleton ``ResilienceCoordinator``.

    Реализация: ``infrastructure.resilience.coordinator.get_resilience_coordinator``.
    """
    if "resilience_coordinator" in _overrides:
        return _overrides["resilience_coordinator"]
    module = resolve_module("resilience.coordinator")
    return module.get_resilience_coordinator()


def set_resilience_coordinator_provider(coordinator: Any) -> None:
    """Установить override для ``resilience_coordinator`` provider."""
    _overrides["resilience_coordinator"] = coordinator


def get_resilience_components_report_provider() -> Any:
    """Возвращает callable ``resilience_components_report`` для health/components."""
    if "resilience_components_report" in _overrides:
        return _overrides["resilience_components_report"]
    module = resolve_module("resilience.health")
    return module.resilience_components_report


def set_resilience_components_report_provider(callable_: Any) -> None:
    """Установить override для ``resilience_components_report`` provider."""
    _overrides["resilience_components_report"] = callable_


# ─────────────── Rate limiter (webhook handler) ───────────────


def get_rate_limiter_provider() -> Any:
    """Возвращает singleton ``RedisRateLimiter`` (см. ``RateLimiterProtocol``)."""
    if "rate_limiter" in _overrides:
        return _overrides["rate_limiter"]
    module = resolve_module("resilience.unified_rate_limiter")
    return module.get_rate_limiter()


def set_rate_limiter_provider(limiter: Any) -> None:
    """Установить override для ``rate_limiter`` provider."""
    _overrides["rate_limiter"] = limiter


def get_rate_limit_classes_provider() -> tuple[Any, Any]:
    """Возвращает классы ``(RateLimit, RateLimitExceeded)`` из infra-модуля."""
    if "rate_limit_classes" in _overrides:
        return _overrides["rate_limit_classes"]
    module = resolve_module("resilience.unified_rate_limiter")
    return module.RateLimit, module.RateLimitExceeded
