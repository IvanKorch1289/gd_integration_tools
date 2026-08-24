"""Sprint 38: resilience facade — re-exports canonical resilience primitives.

R13 FIX (2026-08-30): route resilience primitives to canonical locations.

Three changes vs the pre-R13 version:

1. :class:`CircuitBreaker` — was importing from ``infrastructure.resilience``
   (missing slot after S44 W3 layer migration). Canonical location is
   :mod:`src.backend.core.resilience.breaker` (purgatory backend).

2. :class:`RateLimiter` Protocol — was importing from
   ``infrastructure.resilience`` (missing slot after S44 W3). Canonical
   location is :mod:`src.backend.core.resilience.rate_limiter` (Protocol
   definition; concrete backends stay in infrastructure/).

3. :mod:`unified_rate_limiter` module re-export — required by lazy proxy
   in :mod:`src.backend.services.resilience.rate_limiter`. Concrete
   implementations (RedisRateLimiter, ResourceRateLimiter, get_rate_limiter)
   stay in infrastructure; this facade only re-exports the module so the
   ``__getattr__`` lazy proxy in services layer still works without
   direct services → infrastructure import (which violates layer policy).

Layer policy: entrypoints → services. services → core.api (facade).
core.api → infrastructure (allowed via facade).
"""
from __future__ import annotations

from src.backend.core.resilience.breaker import CircuitBreaker
from src.backend.core.resilience.rate_limiter import RateLimiter
from src.backend.infrastructure.resilience import Bulkhead, unified_rate_limiter

# ``rate_limiter`` symbol is exposed by infrastructure.resilience via
# ``RateLimiterPolicy`` (S217 dataclass) — but the pre-R13 code expected
# a module-level ``rate_limiter`` symbol. Preserve backward compat by
# aliasing to the unified_rate_limiter module (which contains the
# canonical ``get_rate_limiter()`` factory).
rate_limiter = unified_rate_limiter

__all__ = [
    "rate_limiter",
    "unified_rate_limiter",
    "RateLimiter",
    "CircuitBreaker",
    "Bulkhead",
]
