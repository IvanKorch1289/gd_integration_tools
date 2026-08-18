"""Rate limiter facade для entrypoints (S45 W2 + Sprint 224 lazy proxy).

Single entry-point для rate limiter access из entrypoints.
Re-export canonical ``infrastructure.resilience.unified_rate_limiter``.

Sprint 224 refactor: convert direct re-export to ``__getattr__``-based lazy
proxy (ponytail: thin proxy). Устраняет layer-violation
``services → infrastructure``.

Использование::

    from src.backend.services.resilience.rate_limiter import (
        RateLimit, RateLimitExceeded, get_rate_limiter,
    )

Layer policy: entrypoints -> services (allowed per V22).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.infrastructure.resilience.unified_rate_limiter import (
        RateLimit,
        RateLimitExceeded,
        get_rate_limiter,
    )

__all__ = ("RateLimit", "RateLimitExceeded", "get_rate_limiter")


def __getattr__(name: str) -> Any:
    """Lazy proxy: import infrastructure только при lookup атрибута."""
    if name in {"RateLimit", "RateLimitExceeded", "get_rate_limiter"}:
        from src.backend.infrastructure.resilience import (
            unified_rate_limiter as _m,
        )
        return getattr(_m, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
