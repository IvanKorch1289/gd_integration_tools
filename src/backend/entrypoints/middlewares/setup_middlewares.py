from fastapi import FastAPI

__all__ = ("setup_middlewares",)


def setup_middlewares(app: FastAPI) -> None:
    """
    Инициализирует и настраивает цепочку middleware для приложения FastAPI.

    Порядок добавления middleware критически важен:
    1. Метрики и безопасность
    2. Обработка тела запросов
    3. Управление запросами
    4. Обработка ошибок

    Args:
        app (FastAPI): Экземпляр приложения для настройки

    Raises:
        TypeError: При несовместимых типах для middleware
        ValueError: При некорректных значениях в конфигурации
        ImportError: При проблемах импорта компонентов

    Пример:
        app = FastAPI()
        setup_middlewares(app)
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
    from src.backend.entrypoints.middlewares.blocked_routes import (
        BlockedRoutesMiddleware,
    )
    from src.backend.entrypoints.middlewares.data_masking import DataMaskingMiddleware
    from src.backend.entrypoints.middlewares.degradation import DegradationMiddleware
    from src.backend.entrypoints.middlewares.exception_handler import (
        ExceptionHandlerMiddleware,
    )
    from src.backend.entrypoints.middlewares.otel_middleware import OtelMiddleware
    from src.backend.entrypoints.middlewares.request_body_cache import (
        RequestBodyCacheMiddleware,
    )
    from src.backend.entrypoints.middlewares.request_id import RequestIDMiddleware
    from src.backend.entrypoints.middlewares.request_log import (
        InnerRequestLoggingMiddleware,
    )
    from src.backend.entrypoints.middlewares.response_cache import (
        ResponseCacheMiddleware,
    )
    from src.backend.entrypoints.middlewares.timeout import TimeoutMiddleware

    # Порядок оптимизирован для high-load:
    # 1. Дешёвые проверки + early exit (отсекаем до обработки)
    # 2. Управление запросом (ID, timeout)
    # 3. Бизнес-middleware (кэш, маскировка)
    # 4. Метрики (измеряют реальную работу, а не overhead)
    middleware_chain = [
        # Слой 1: Early exit — отклоняем невалидные запросы мгновенно
        (ExceptionHandlerMiddleware, {}),
        (
            CORSMiddleware,
            {
                "allow_origins": settings.secure.cors_origins,
                "allow_credentials": settings.secure.cors_allow_credentials,
                "allow_methods": settings.secure.cors_allow_methods,
                "allow_headers": settings.secure.cors_allow_headers,
                "expose_headers": ["X-Request-ID"],
                "max_age": 600,
            },
        ),
        (TrustedHostMiddleware, {"allowed_hosts": settings.secure.allowed_hosts}),
        (BlockedRoutesMiddleware, {}),
        (IPRestrictionMiddleware, {}),
        (APIKeyMiddleware, {}),
        # Слой 2: Управление запросом
        # NOTE: CircuitBreakerMiddleware удалён в A2 (ADR-005) — global-state баг.
        # Circuit breaker применяется per-route на уровне HTTP-клиентов.
        (RequestIDMiddleware, {}),
        # W26.5: блокирует POST/PUT/PATCH/DELETE при degraded db_main
        # (sqlite_ro fallback). Стоит ПОСЛЕ RequestID (для трассировки)
        # и ПЕРЕД RequestBodyCache (чтобы не читать body заблокированных
        # запросов).
        (DegradationMiddleware, {}),
        # IL-OBS1 (ADR-032): кешируем body один раз, чтобы downstream
        # middleware (audit_log / audit_replay / request_log) читали
        # `request.state.body` вместо повторного `await request.body()`.
        (RequestBodyCacheMiddleware, {}),
        (TimeoutMiddleware, {}),
        # Слой 3: Обработка тела (только для прошедших аутентификацию)
        (ResponseCacheMiddleware, {"max_age": 60}),
        (
            GZipMiddleware,
            {
                "minimum_size": settings.app.gzip_minimum_size,
                "compresslevel": settings.app.gzip_compresslevel,
            },
        ),
        (DataMaskingMiddleware, {}),
        # Wave 8.1: маркер успешной аутентификации в response.
        (AuthMethodHeaderMiddleware, {}),
        # Слой 4: Логирование и метрики (последними — измеряют всё)
        (AuditLogMiddleware, {}),
        (AuditReplayMiddleware, {"sample_rate": 1.0}),  # ARCH-4: wire audit_replay
        (InnerRequestLoggingMiddleware, {}),
        # IL-OBS1 (ADR-032): FastAPI OTEL middleware — создаёт HTTP-span
        # с correlation/tenant/route_id атрибутами и пропагирует
        # `traceparent` в response headers. Ставится ПОСЛЕ логов и
        # ПЕРЕД PrometheusMiddleware, чтобы измерять полный цикл.
        (OtelMiddleware, {}),
        (PrometheusMiddleware, {"group_paths": True, "app_name": settings.app.title}),
    ]

    try:
        for middleware, options in middleware_chain:
            app.add_middleware(middleware, **options)
    except TypeError as exc:
        raise RuntimeError(
            f"Ошибка конфигурации middleware {middleware.__name__}: {str(exc)}"
        ) from exc
