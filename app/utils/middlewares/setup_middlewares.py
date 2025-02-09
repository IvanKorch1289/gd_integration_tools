from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette_exporter import PrometheusMiddleware

from app.config.settings import settings
from app.utils.middlewares.circuit_breaker import CircuitBreakerMiddleware
from app.utils.middlewares.request_id import RequestIDMiddleware
from app.utils.middlewares.request_log import InnerRequestLoggingMiddleware
from app.utils.middlewares.security_headers import SecurityHeadersMiddleware
from app.utils.middlewares.timeout import TimeoutMiddleware


__all__ = ("setup_middlewares",)


async def setup_middlewares(app: FastAPI) -> None:
    middleware_chain = [
        (PrometheusMiddleware, {}),
        (
            TrustedHostMiddleware,
            {"allowed_hosts": settings.auth.allowed_hosts},
        ),
        (SecurityHeadersMiddleware, {}),
        (GZipMiddleware, {"minimum_size": 1000}),
        (RequestIDMiddleware, {}),
        (TimeoutMiddleware, {}),
        (
            InnerRequestLoggingMiddleware,
            {"log_body": True, "max_body_size": 4096},
        ),
        (CircuitBreakerMiddleware, {}),
    ]

    for middleware, options in middleware_chain:
        app.add_middleware(middleware, **options)
