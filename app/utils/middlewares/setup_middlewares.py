from fastapi import FastAPI


__all__ = ("setup_middlewares",)


def setup_middlewares(app: FastAPI) -> None:
    from fastapi.middleware.gzip import GZipMiddleware
    from fastapi.middleware.trustedhost import TrustedHostMiddleware
    from starlette_exporter import PrometheusMiddleware

    from app.config.settings import settings
    from app.utils.middlewares.circuit_breaker import CircuitBreakerMiddleware
    from app.utils.middlewares.request_id import RequestIDMiddleware
    from app.utils.middlewares.request_log import InnerRequestLoggingMiddleware
    from app.utils.middlewares.timeout import TimeoutMiddleware

    middleware_chain = [
        (PrometheusMiddleware, {}),
        (
            TrustedHostMiddleware,
            {"allowed_hosts": settings.auth.allowed_hosts},
        ),
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
