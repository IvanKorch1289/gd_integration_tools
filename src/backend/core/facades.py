"""Unified middleware facades (S171 M7 — integration layer).

Единая точка импорта для auth/limits/CB/cache/timeout/retry/bulkhead
across all layers (HTTP middleware, DSL processors, services).

Ponytail (D160): thin wrapper module, re-exports canonical implementations
с lazy loading (избегаем circular import в существующей infra).
"""
from __future__ import annotations

# Auth facade
from src.backend.core.security.authorization_gateway import (
    AuthorizationGateway,
)
from src.backend.core.security.capabilities import CapabilityGate
from src.backend.core.security.pii_tokenizer import PIITokenizer
from src.backend.core.di.providers.ai import get_pii_tokenizer_provider

# Timeout + Retry (core/utils, no circular issues)
from src.backend.core.utils.timeout_helper import (
    async_timeout,
    with_timeout,
)
from src.backend.core.utils.retry_helper import (
    default_retryable,
    retry_async,
)

# CB + Cache + Rate limit + Bulkhead — lazy import (project has circular deps)
__all__ = (
    # Auth (eager)
    "AuthorizationGateway",
    "CapabilityGate",
    "PIITokenizer",
    "get_pii_tokenizer_provider",
    # Timeout (eager)
    "with_timeout",
    "async_timeout",
    # Retry (eager)
    "retry_async",
    "default_retryable",
    # Rate limit (lazy — see __getattr__)
    "RateLimit",
    "RedisRateLimiter",
    "get_rate_limiter",
    "RateLimitExceeded",
    # CB (lazy)
    "ClientCircuitBreaker",
    # Bulkhead (lazy)
    "Bulkhead",
    "BulkheadExhausted",
    "BulkheadDefaults",
)


def __getattr__(name: str) -> object:
    """Lazy import для модулей с circular dependencies (M7).

    Реальный набор: 16 primitives (9 eager + 7 lazy).
    """
    if name in ("RateLimit", "RedisRateLimiter", "get_rate_limiter", "RateLimitExceeded"):
        from src.backend.infrastructure.resilience import unified_rate_limiter as _m
        return getattr(_m, name)
    if name in ("ClientCircuitBreaker",):
        from src.backend.infrastructure.resilience import client_breaker as _m
        return getattr(_m, name)
    if name in ("Bulkhead", "BulkheadExhausted", "BulkheadDefaults"):
        from src.backend.infrastructure.resilience import bulkhead as _m
        return getattr(_m, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """Поддержка dir(facades) для tooling (P1-1 fix)."""
    return list(__all__)
