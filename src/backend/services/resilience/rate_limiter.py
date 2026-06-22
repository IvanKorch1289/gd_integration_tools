"""Rate limiter facade для entrypoints (S45 W2).

Single entry-point для rate limiter access из entrypoints.
Re-export canonical ``infrastructure.resilience.unified_rate_limiter``.

Использование::

    from src.backend.services.resilience.rate_limiter import (
        RateLimit, RateLimitExceeded, get_rate_limiter,
    )

Layer policy: entrypoints -> services (allowed per V22).
"""
from __future__ import annotations

from src.backend.infrastructure.resilience.unified_rate_limiter import (  # noqa: E402,F401
    RateLimit,
    RateLimitExceeded,
    get_rate_limiter,
)

__all__ = ("RateLimit", "RateLimitExceeded", "get_rate_limiter")
