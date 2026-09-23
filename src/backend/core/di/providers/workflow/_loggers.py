"""Logger providers — app/grpc/stream + correlation setter (W9 P2-13 Phase 7).

W9 P2-13 Phase 7 (cycle 153): извлечено из ``core/di/providers/workflow.py``
(602 LOC god-module). Содержит structured logger providers + correlation context
setter.

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


# ─────────────── App/grpc/stream loggers (entrypoints/middlewares) ───────────────


def get_app_logger_provider() -> Any:
    """Возвращает singleton ``app_logger`` (структурированный logger).

    Используется в audit_log / request_log / timeout middlewares.
    """
    if "app_logger" in _overrides:
        return _overrides["app_logger"]
    module = resolve_module("external_apis.logging_service")
    return module.app_logger


def set_app_logger_provider(logger: Any) -> None:
    """Установить override для ``app_logger`` provider."""
    _overrides["app_logger"] = logger


def get_correlation_context_setter_provider() -> Any:
    """Возвращает callable ``set_correlation_context`` (contextvar-setter).

    Используется в TenantMiddleware для передачи tenant_id в logging-контекст.
    """
    if "correlation_context_setter" in _overrides:
        return _overrides["correlation_context_setter"]
    module = resolve_module("observability.correlation")
    return module.set_correlation_context


def set_correlation_context_setter_provider(setter: Any) -> None:
    """Установить override для ``correlation_context_setter`` provider."""
    _overrides["correlation_context_setter"] = setter


def get_grpc_logger_provider() -> Any:
    """Возвращает ``grpc_logger`` из ``logging_service``."""
    if "grpc_logger" in _overrides:
        return _overrides["grpc_logger"]
    module = resolve_module("external_apis.logging_service")
    return module.grpc_logger


def set_grpc_logger_provider(logger: Any) -> None:
    """Установить override для ``grpc_logger`` provider."""
    _overrides["grpc_logger"] = logger


def get_stream_logger_provider() -> Any:
    """Возвращает ``stream_logger`` из ``logging_service``."""
    if "stream_logger" in _overrides:
        return _overrides["stream_logger"]
    module = resolve_module("external_apis.logging_service")
    return module.stream_logger


def set_stream_logger_provider(logger: Any) -> None:
    """Установить override для ``stream_logger`` provider."""
    _overrides["stream_logger"] = logger
