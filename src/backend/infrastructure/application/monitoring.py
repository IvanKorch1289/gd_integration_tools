"""Prometheus monitoring for FastAPI — custom implementation replacing
prometheus-fastapi-instrumentator (incompatible with starlette>=1.0).

Provides the same HTTP metrics: request count, latency histogram,
in-progress requests gauge. Exposes /metrics endpoint.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from src.backend.core.utils.metrics_registry import metrics_registry

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send

__all__ = ("setup_monitoring",)

# Metrics — registered once via MetricsRegistry (idempotent, prevents duplicates).
_request_count = metrics_registry.counter(
    "http_requests_total",
    "Total HTTP request count",
    labels=("method", "path", "status_code"),
)
_request_latency = metrics_registry.histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    labels=("method", "path"),
    buckets=(
        0.005,
        0.01,
        0.025,
        0.05,
        0.075,
        0.1,
        0.25,
        0.5,
        0.75,
        1.0,
        2.5,
        5.0,
        7.5,
        10.0,
    ),
)
_requests_in_progress = metrics_registry.gauge(
    "http_requests_in_progress",
    "Number of HTTP requests currently in progress",
    labels=("method", "path"),
)


class PrometheusMiddleware:
    """ASGI middleware that collects request metrics for Prometheus.

    Drop-in replacement for ``prometheus-fastapi-instrumentator`` that works
    with starlette>=1.0.
    """

    def __init__(self, app: "ASGIApp") -> None:
        self.app = app

    async def __call__(self, scope: "Scope", receive: "Receive", send: "Send") -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "UNKNOWN")
        path = self._normalize_path(scope)
        labels = {"method": method, "path": path}

        _requests_in_progress.labels(**labels).inc()
        start = time.perf_counter()
        status_code = "500"

        async def send_wrapper(message: dict) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = str(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            _requests_in_progress.labels(**labels).dec()
            duration = time.perf_counter() - start
            _request_count.labels(
                method=method, path=path, status_code=status_code
            ).inc()
            _request_latency.labels(method=method, path=path).observe(duration)

    @staticmethod
    def _normalize_path(scope: "Scope") -> str:
        """Return a templated path, excluding /metrics."""
        path = scope.get("path", "/")
        if path == "/metrics":
            return "/metrics"
        return path or "/"


async def metrics_endpoint(scope: "Scope", receive: "Receive", send: "Send") -> None:
    """ASGI handler for GET /metrics — returns Prometheus text format."""
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", CONTENT_TYPE_LATEST.encode())],
        }
    )
    await send({"type": "http.response.body", "body": generate_latest()})


def setup_monitoring(app: "ASGIApp") -> None:
    """
    Настраивает Prometheus metrics для FastAPI.

    Заменяет ``prometheus-fastapi-instrumentator`` (несовместим с starlette>=1.0).
    Собирает: request count, latency histogram, in-progress gauge.
    Эндпоинт /metrics доступен для Prometheus scrape.
    """
    from starlette.routing import Route

    # Add ASGI middleware
    app.add_middleware(PrometheusMiddleware)

    # Mount /metrics route (ASGI-level, not FastAPI route)
    app.routes.append(Route("/metrics", metrics_endpoint, methods=["GET"]))
