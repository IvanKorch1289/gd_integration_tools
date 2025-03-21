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

    from app.config.settings import settings
    from app.utils.middlewares.admin_ip import IPRestrictionMiddleware
    from app.utils.middlewares.api_key import APIKeyMiddleware
    from app.utils.middlewares.blocked_routes import BlockedRoutesMiddleware
    from app.utils.middlewares.circuit_breaker import CircuitBreakerMiddleware
    from app.utils.middlewares.exception_handler import (
        ExceptionHandlerMiddleware,
    )
    from app.utils.middlewares.request_id import RequestIDMiddleware
    from app.utils.middlewares.request_log import InnerRequestLoggingMiddleware
    from app.utils.middlewares.timeout import TimeoutMiddleware

    # Порядок middleware соответствует последовательности обработки запроса
    middleware_chain = [
        # Системные middleware (безопасность и метрики)
        (
            PrometheusMiddleware,
            {"group_paths": True, "app_name": settings.app.title},
        ),
        (
            TrustedHostMiddleware,
            {"allowed_hosts": settings.secure.allowed_hosts},
        ),
        (IPRestrictionMiddleware, {}),
        (APIKeyMiddleware, {}),
        (BlockedRoutesMiddleware, {}),
        (
            GZipMiddleware,
            {
                "minimum_size": settings.app.gzip_minimum_size,
                "compresslevel": settings.app.gzip_compresslevel,
            },
        ),
        # Middleware управления запросами
        (RequestIDMiddleware, {}),
        (TimeoutMiddleware, {}),
        # Middleware логирования
        (
            InnerRequestLoggingMiddleware,
            {},
        ),
        # Middleware обработки ошибок
        (CircuitBreakerMiddleware, {}),
        (ExceptionHandlerMiddleware, {}),
    ]

    try:
        for middleware, options in middleware_chain:
            app.add_middleware(middleware, **options)
    except TypeError as exc:
        raise RuntimeError(
            f"Ошибка конфигурации middleware {middleware.__name__}: {str(exc)}"
        ) from exc
