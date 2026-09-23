"""RateLimiter — token bucket для external API protection (Wave 4 P2.14b).

Token bucket algorithm:
- Bucket with capacity `max_tokens` filled at `refill_rate` per second.
- Each call `acquire()` consumes 1 token (configurable `cost`).
- If no tokens, blocks (async) or returns False immediately.

Pure-Python stdlib: uses `time.monotonic()` + `asyncio.Event` для
async coordination. Без external deps.

Использование::

    from src.backend.core.rate_limiter import (  # noqa: F401 — re-export
        RateLimiter, RateLimiterConfig, get_rate_limiter,
    )

    limiter = get_rate_limiter(
        "skb_api",
        RateLimiterConfig(max_tokens=10, refill_rate=2.0),
    )

    if await limiter.acquire():
        # Make API call.
    else:
        # Rate limited, retry later.

    # Or sync version.
    if limiter.try_acquire():
        # OK
"""

from __future__ import annotations

from src.backend.core.rate_limiter.limiter import (  # noqa: F401 — re-export
    AsyncRateLimiter,
    RateLimiter,
    RateLimiterConfig,
    get_rate_limiter,
)

__all__ = ("AsyncRateLimiter", "RateLimiter", "RateLimiterConfig", "get_rate_limiter")
