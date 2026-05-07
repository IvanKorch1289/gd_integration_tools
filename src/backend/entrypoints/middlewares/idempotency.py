"""Idempotency-Key middleware (Sprint 0 #12, V5 security constraint).

Тонкая обёртка над ``asgi_idempotency_header.IdempotencyHeaderMiddleware``.
Применяется ко всем POST/PATCH endpoints; при повторном запросе с тем
же ``Idempotency-Key`` возвращает закешированный ответ из Redis.
"""

from __future__ import annotations

from idempotency_header_middleware import IdempotencyHeaderMiddleware

__all__ = ("IdempotencyHeaderMiddleware", "IDEMPOTENCY_HEADER")

IDEMPOTENCY_HEADER = "Idempotency-Key"
