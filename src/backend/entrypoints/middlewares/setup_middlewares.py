"""Настройка цепочки ASGI middleware через :class:`MiddlewareRegistry`.

S17 ADR-NEW-2: built-in middleware регистрируются в реестре с явным
``order``, плагины могут расширять цепочку через ``plugin.toml``
``[[middleware]]`` или entry-points ``gd_integration_tools.middleware_hooks``.

Внешний API :func:`setup_middlewares` неизменён — внутри он строит
:class:`MiddlewareRegistry`, регистрирует 25+ built-in middleware с
ordering'ом по слоям и вызывает ``apply_to_app``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

    from src.backend.entrypoints.middlewares.registry import MiddlewareRegistry

__all__ = ("build_default_registry", "setup_middlewares")


def build_default_registry() -> MiddlewareRegistry:
    """Сконструировать ``MiddlewareRegistry`` с предзаполненными built-in.

    Order распределён по 4 слоям:

    * Layer 1 (early exit, 0-249) — отсекаем невалидные запросы до работы.
    * Layer 2 (request mgmt, 250-499) — ID, tenant, context, idempotency, timeout.
    * Layer 3 (body/auth, 500-749) — cache, compression, masking, auth.
    * Layer 4 (logging/metrics, 750-999) — audit, OTel, Prometheus.

    Порядок применения совпадает с историческим жёстким списком.
    """
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.middleware.gzip import GZipMiddleware
    from fastapi.middleware.trustedhost import TrustedHostMiddleware
    from starlette_exporter import PrometheusMiddleware

    from src.backend.core.config.settings import settings
    from src.backend.entrypoints.middlewares.admin_ip import IPRestrictionMiddleware
    from src.backend.entrypoints.middlewares.api_key import APIKeyMiddleware
    from src.backend.entrypoints.middlewares.audit_log import AuditLogMiddleware
    from src.backend.entrypoints.middlewares.audit_replay import AuditReplayMiddleware
    from src.backend.entrypoints.middlewares.auth_method_header import (
        AuthMethodHeaderMiddleware,
    )
    from src.backend.entrypoints.middlewares.auth_required import AuthRequiredMiddleware
    from src.backend.entrypoints.middlewares.blocked_routes import (
        BlockedRoutesMiddleware,
    )
    from src.backend.entrypoints.middlewares.brotli_compression import (
        BrotliCompressionMiddleware,
    )
    from src.backend.entrypoints.middlewares.circuit_breaker import (
        BreakerPolicy,
        CircuitBreakerMiddleware,  # S81 W2: restored
    )
    from src.backend.entrypoints.middlewares.correlation import CorrelationIdMiddleware
    from src.backend.entrypoints.middlewares.data_masking import DataMaskingMiddleware
    from src.backend.entrypoints.middlewares.degradation import DegradationMiddleware
    from src.backend.entrypoints.middlewares.exception_handler import (
        ExceptionHandlerMiddleware,
    )
    from src.backend.entrypoints.middlewares.global_ratelimit import (
        GlobalRateLimitMiddleware,
        build_rate_limit_checker,
    )
    from src.backend.entrypoints.middlewares.idempotency import (
        IdempotencyHeaderMiddleware,
        build_idempotency_backend,
    )
    from src.backend.entrypoints.middlewares.otel_middleware import OtelMiddleware
    from src.backend.entrypoints.middlewares.registry import MiddlewareRegistry
    from src.backend.entrypoints.middlewares.request_body_cache import (
        RequestBodyCacheMiddleware,
    )
    from src.backend.entrypoints.middlewares.request_context import (
        RequestContextMiddleware,
    )
    from src.backend.entrypoints.middlewares.request_id import RequestIDMiddleware
    from src.backend.entrypoints.middlewares.request_log import (
        InnerRequestLoggingMiddleware,
    )
    from src.backend.entrypoints.middlewares.response_cache import (
        ResponseCacheMiddleware,
    )
    from src.backend.entrypoints.middlewares.security_headers import (
        SecurityHeadersMiddleware,
    )
    from src.backend.entrypoints.middlewares.tenant import TenantMiddleware
    from src.backend.entrypoints.middlewares.timeout import TimeoutMiddleware

    registry = MiddlewareRegistry()

    # Layer 1: early exit (0-249) ------------------------------------------ #
    registry.register_builtin("exception_handler", ExceptionHandlerMiddleware, order=10)
    registry.register_builtin(
        "global_ratelimit",
        GlobalRateLimitMiddleware,
        {"checker": build_rate_limit_checker()},
        order=20,
    )
    registry.register_builtin(
        "cors",
        CORSMiddleware,
        {
            "allow_origins": settings.secure.cors_origins,
            "allow_credentials": settings.secure.cors_allow_credentials,
            "allow_methods": settings.secure.cors_allow_methods,
            "allow_headers": settings.secure.cors_allow_headers,
            "expose_headers": ["X-Request-ID"],
            "max_age": 600,
        },
        order=30,
    )
    registry.register_builtin(
        "trusted_host",
        TrustedHostMiddleware,
        {"allowed_hosts": settings.secure.allowed_hosts},
        order=50,
    )
    registry.register_builtin("blocked_routes", BlockedRoutesMiddleware, order=70)
    registry.register_builtin("ip_restriction", IPRestrictionMiddleware, order=90)
    registry.register_builtin("api_key", APIKeyMiddleware, order=110)

    # Layer 2: request management (250-499) -------------------------------- #
    # S81 W2: CircuitBreakerMiddleware RESTORED (FINAL_REPORT_V2 P1 #8).
    # Removed в A2 (ADR-005) — global-state bug. S81 design:
    # per-route state, sliding window, BreakerPolicy config (NO global).
    # Order=250: early enough to reject unhealthy upstreams before
    # processing.
    registry.register_builtin(
        "circuit_breaker",
        CircuitBreakerMiddleware,
        {
            "default_policy": BreakerPolicy(
                failure_threshold=5,
                window_seconds=60.0,
                reset_timeout=30.0,
            ),
        },
        order=250,
    )
    registry.register_builtin("request_id", RequestIDMiddleware, order=260)
    # Sprint 0 #12: correlation-id propagation (X-Correlation-ID header).
    registry.register_builtin("correlation_id", CorrelationIdMiddleware, order=280)
    # Sprint 1 V16: tenant_id propagation (X-Tenant-ID → contextvar).
    registry.register_builtin("tenant", TenantMiddleware, order=300)
    # S17 ADR-NEW-3: unified RequestContext snapshot (после tenant).
    registry.register_builtin("request_context", RequestContextMiddleware, order=320)
    # Sprint 0 #12 + V5: Idempotency-Key для POST/PATCH (Redis backend).
    registry.register_builtin(
        "idempotency",
        IdempotencyHeaderMiddleware,
        {"backend": build_idempotency_backend()},
        order=340,
    )
    # W26.5: блокирует POST/PUT/PATCH/DELETE при degraded db_main.
    registry.register_builtin("degradation", DegradationMiddleware, order=360)
    # IL-OBS1 (ADR-032): кэш body для downstream middleware.
    registry.register_builtin(
        "request_body_cache", RequestBodyCacheMiddleware, order=380
    )
    registry.register_builtin("timeout", TimeoutMiddleware, order=400)

    # Layer 3: body / auth (500-749) --------------------------------------- #
    registry.register_builtin(
        "response_cache", ResponseCacheMiddleware, {"max_age": 60}, order=520
    )
    if settings.app.compression_brotli:
        # S10 K2 W2 (PERF-6.6): Brotli compression — действует выше GZIP.
        registry.register_builtin(
            "brotli",
            BrotliCompressionMiddleware,
            {
                "minimum_size": settings.app.brotli_minimum_size,
                "quality": settings.app.brotli_quality,
            },
            order=540,
        )
    registry.register_builtin(
        "gzip",
        GZipMiddleware,
        {
            "minimum_size": settings.app.gzip_minimum_size,
            "compresslevel": settings.app.gzip_compresslevel,
        },
        order=560,
    )
    registry.register_builtin("data_masking", DataMaskingMiddleware, order=580)
    # Wave 8.1: маркер успешной аутентификации в response.
    registry.register_builtin(
        "auth_method_header", AuthMethodHeaderMiddleware, order=600
    )
    # V7: глобальный defense-in-depth auth-guard.
    registry.register_builtin("auth_required", AuthRequiredMiddleware, order=620)

    # Layer 4: logging / metrics (750-999) --------------------------------- #
    registry.register_builtin("audit_log", AuditLogMiddleware, order=760)
    registry.register_builtin(
        "audit_replay", AuditReplayMiddleware, {"sample_rate": 1.0}, order=780
    )
    registry.register_builtin(
        "inner_request_logging", InnerRequestLoggingMiddleware, order=800
    )
    # IL-OBS1 (ADR-032): FastAPI OTEL middleware — HTTP-span с tenant/route_id.
    registry.register_builtin("otel", OtelMiddleware, order=820)
    registry.register_builtin(
        "prometheus",
        PrometheusMiddleware,
        {"group_paths": True, "app_name": settings.app.title},
        order=840,
    )
    registry.register_builtin("security_headers", SecurityHeadersMiddleware, order=860)

    return registry


def setup_middlewares(app: FastAPI) -> None:
    """Инициализирует и настраивает цепочку middleware для FastAPI.

    Делегирует регистрацию :class:`MiddlewareRegistry` (S17 ADR-NEW-2).
    Built-in 25+ middleware распределены по 4 слоям через ``order``,
    плагины расширяют цепочку через ``plugin.toml`` или entry-points.

    Args:
        app: Экземпляр FastAPI для настройки.

    Raises:
        RuntimeError: При несовместимых типах для middleware.
    """
    registry = build_default_registry()
    try:
        registry.register_from_entry_points()
    except ValueError as exc:
        raise RuntimeError(f"Ошибка загрузки middleware entry-points: {exc}") from exc
    try:
        registry.apply_to_app(app)
    except TypeError as exc:
        raise RuntimeError(f"Ошибка конфигурации middleware: {exc}") from exc
