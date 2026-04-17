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
    from fastapi.middleware.gzip import GZipMiddleware
    from fastapi.middleware.trustedhost import TrustedHostMiddleware
    from starlette_exporter import PrometheusMiddleware

    from app.core.config.settings import settings
    from app.entrypoints.middlewares.admin_ip import IPRestrictionMiddleware
    from app.entrypoints.middlewares.api_key import APIKeyMiddleware
    from app.entrypoints.middlewares.blocked_routes import BlockedRoutesMiddleware
    from app.entrypoints.middlewares.circuit_breaker import CircuitBreakerMiddleware
    from app.entrypoints.middlewares.exception_handler import (
        ExceptionHandlerMiddleware,
    )
    from app.entrypoints.middlewares.audit_log import AuditLogMiddleware
    from app.entrypoints.middlewares.data_masking import DataMaskingMiddleware
    from app.entrypoints.middlewares.request_id import RequestIDMiddleware
    from app.entrypoints.middlewares.request_log import (
        InnerRequestLoggingMiddleware,
    )
    from app.entrypoints.middlewares.response_cache import ResponseCacheMiddleware
    from app.entrypoints.middlewares.timeout import TimeoutMiddleware

    # Порядок оптимизирован для high-load:
    # 1. Дешёвые проверки + early exit (отсекаем до обработки)
    # 2. Управление запросом (ID, timeout)
    # 3. Бизнес-middleware (кэш, маскировка)
    # 4. Метрики (измеряют реальную работу, а не overhead)
    middleware_chain = [
        # Слой 1: Early exit — отклоняем невалидные запросы мгновенно
        (ExceptionHandlerMiddleware, {}),
        (TrustedHostMiddleware, {"allowed_hosts": settings.secure.allowed_hosts}),
        (BlockedRoutesMiddleware, {}),
        (IPRestrictionMiddleware, {}),
        (APIKeyMiddleware, {}),
        # Слой 2: Управление запросом
        (RequestIDMiddleware, {}),
        (TimeoutMiddleware, {}),
        (CircuitBreakerMiddleware, {}),
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
        # Слой 4: Логирование и метрики (последними — измеряют всё)
        (AuditLogMiddleware, {}),
        (InnerRequestLoggingMiddleware, {}),
        (PrometheusMiddleware, {"group_paths": True, "app_name": settings.app.title}),
    ]

    try:
        for middleware, options in middleware_chain:
            app.add_middleware(middleware, **options)
    except TypeError as exc:
        raise RuntimeError(
            f"Ошибка конфигурации middleware {middleware.__name__}: {str(exc)}"
        ) from exc
