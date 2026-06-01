"""Correlation-ID middleware (Sprint 0 #12).

Тонкая обёртка над ``asgi_correlation_id.CorrelationIdMiddleware``.
Прокидывает заголовок ``X-Correlation-ID`` сквозь все слои и логирует
его через structlog (см. ``infrastructure/logging``).
"""

from __future__ import annotations

from asgi_correlation_id import CorrelationIdMiddleware

__all__ = ("CorrelationIdMiddleware", "CORRELATION_HEADER")

CORRELATION_HEADER = "X-Correlation-ID"
