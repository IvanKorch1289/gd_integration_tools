"""Unified middleware facades (S171 M7 — integration layer).

Единая точка импорта для auth/limits/CB/cache/timeout/retry/bulkhead
across all layers (HTTP middleware, DSL processors, services).

Ponytail (D160): thin wrapper module, eager re-exports canonical
implementations (post S204 retry canonicalization) + lazy mapping для
модулей с circular dependencies (rate_limit/CB/bulkhead).
"""
# ruff: noqa: F822  # lazy __getattr__ exports verified by runtime test (tests/unit/core/test_facades.py); rate_limit/CB/bulkhead deferred to avoid circular deps with infrastructure.resilience
from __future__ import annotations

from src.backend.core.di.providers.ai import get_pii_tokenizer_provider
from src.backend.core.resilience.retry import default_retryable, retry_async

# Auth facade
from src.backend.core.security.authorization_gateway import AuthorizationGateway
from src.backend.core.security.capabilities import CapabilityGate
from src.backend.core.security.pii_tokenizer import PIITokenizer

# Timeout (core/utils, no circular issues)
from src.backend.core.utils.timeout_helper import with_timeout

# CB + Cache + Rate limit + Bulkhead — lazy import (project has circular deps)
__all__ = (
    # Auth (eager)
    "AuthorizationGateway",
    "CapabilityGate",
    "PIITokenizer",
    "get_pii_tokenizer_provider",
    # Timeout (eager)
    "with_timeout",
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
        from src.backend.infrastructure.resilience import (
            unified_rate_limiter as _rate_limit_module,
        )

        return getattr(_rate_limit_module, name)
    if name in ("ClientCircuitBreaker",):
        from src.backend.infrastructure.resilience import (
            client_breaker as _breaker_module,
        )

        return getattr(_breaker_module, name)
    if name in ("Bulkhead", "BulkheadExhausted", "BulkheadDefaults"):
        from src.backend.infrastructure.resilience import bulkhead as _bulkhead_module
        return getattr(_bulkhead_module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """Поддержка dir(facades) для tooling (P1-1 fix)."""
    return list(__all__)
