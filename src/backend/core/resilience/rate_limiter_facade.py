"""S104 W2 — Rate limiter facade canonical location.

DEEP-RESEARCH §3.9 claim "Rate limiting 3 implementations split-brain 🟡"
(2026-06-12) — частично УСТАРЕВШИЙ. Unified facade уже существует:
* ``src/backend/infrastructure/resilience/unified_rate_limiter.py:137`` —
  ``get_rate_limiter()`` singleton (Redis-backed token bucket).
* Per-ADR Section 1.1, ``ResilienceCoordinator`` is planned (not yet
  implemented; multi-sprint scope).

Текущие 3 implementation:
1. ``entrypoints/middlewares/global_ratelimit.py:RateLimitChecker`` —
   per-IP middleware (FakeRateLimitChecker / RedisRateLimitChecker).
2. ``infrastructure/resilience/rate_limiter.py:ResourceRateLimiter`` —
   component-level rate limit (per-API-key).
3. ``infrastructure/notifications/priority.py`` — per-tenant pool
   priorities (not true rate limiter, but related).

S104 W2 = canonical re-export of unified facade через ``core/`` —
аналогично S95 W4 AuthGateway + S103 W3 AuditFacade pattern.
Real ResilienceCoordinator consolidation — S105+ (multi-sprint).
"""

from __future__ import annotations

# Canonical re-export of unified rate limiter.
from src.backend.infrastructure.resilience.unified_rate_limiter import (  # noqa: F401
    RateLimit,
    RateLimitExceeded,
    RedisRateLimiter,
    get_rate_limiter,
)

__all__ = ("RateLimit", "RateLimitExceeded", "RedisRateLimiter", "get_rate_limiter")
