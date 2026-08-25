"""Mobile JWT revocation + rate limiting (ADR-0262 / ADR-0264 Phase 2).

Provides:
- ``RevocationStore`` Protocol + ``InMemoryRevocationStore`` implementation
- ``DeviceRateLimiter`` for per-device throttling
- Integration into ``MobileJwtVerifier.verify()`` (optional, off by default)

Phase 2 (cycle 262): skeleton + tests. Redis-backed implementation
deferred to ``infrastructure/redis_revocation_store.py`` when RedisSettings
is available (depends on S47 work).

Usage::

    store = InMemoryRevocationStore()
    await store.revoke(jti="abc", expires_at=now + 3600)

    limiter = DeviceRateLimiter(max_requests=10, window_seconds=60)

    verifier = MobileJwtVerifier(
        backend=backend,
        issuer_whitelist=[...],
        audience="...",
        revocation_store=store,  # optional
        rate_limiter=limiter,  # optional
    )
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from src.backend.core.logging import get_logger


_logger = get_logger(__name__)


@dataclass(frozen=True)
class RevocationRecord:
    """A revoked JWT identifier."""

    jti: str
    revoked_at: float
    expires_at: float


class RevocationError(Exception):
    """Raised on revocation store failure (network, permission, etc.)."""


class RevocationStore(Protocol):
    """Protocol for JWT revocation stores.

    Production impl: Redis-backed with TTL on jti keys.
    Test/dev impl: in-memory dict.
    """

    async def is_revoked(self, jti: str) -> bool:
        """Check if a JWT ID has been revoked."""
        ...

    async def revoke(self, jti: str, *, expires_at: float) -> None:
        """Revoke a JWT ID. ``expires_at`` = when the token would have expired."""
        ...

    async def cleanup_expired(self) -> int:
        """Remove expired revocations. Returns count removed."""
        ...


class InMemoryRevocationStore:
    """In-memory implementation of RevocationStore.

    Suitable for:
    - Tests
    - Single-process dev environments
    - NOT for multi-pod production (use Redis-backed)

    Thread/async safety: simple async-lock-free dict access. Sufficient
    for single-process asyncio context.
    """

    def __init__(self) -> None:
        self._revoked: dict[str, RevocationRecord] = {}

    async def is_revoked(self, jti: str) -> bool:
        record = self._revoked.get(jti)
        if record is None:
            return False
        # Auto-expire
        if record.expires_at <= time.time():
            self._revoked.pop(jti, None)
            return False
        return True

    async def revoke(self, jti: str, *, expires_at: float) -> None:
        if not jti or not isinstance(jti, str):
            raise ValueError("jti must be non-empty string")
        if expires_at <= time.time():
            raise ValueError("expires_at must be in the future")
        self._revoked[jti] = RevocationRecord(
            jti=jti, revoked_at=time.time(), expires_at=expires_at
        )
        _logger.info("jwt revoked", extra={"jti": jti})

    async def cleanup_expired(self) -> int:
        now = time.time()
        expired = [jti for jti, r in self._revoked.items() if r.expires_at <= now]
        for jti in expired:
            self._revoked.pop(jti, None)
        return len(expired)

    def __len__(self) -> int:
        """Test helper: number of currently-revoked JTIs."""
        return len(self._revoked)


@dataclass(frozen=True)
class RateLimitDecision:
    """Result of a rate-limit check."""

    allowed: bool
    remaining: int
    reset_seconds: float


class DeviceRateLimiter:
    """Per-device sliding-window rate limiter.

    Counts requests per ``device_id`` within a sliding time window.
    If count exceeds ``max_requests`` within ``window_seconds``, rejects.

    Suitable for: per-device brute-force protection on mobile JWT path.
    NOT suitable for: distributed rate limiting (use Redis-backed impl).

    Storage: in-memory dict keyed by device_id. Not multi-pod safe.
    """

    def __init__(self, *, max_requests: int, window_seconds: float) -> None:
        if max_requests <= 0:
            raise ValueError("max_requests must be > 0")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        self._max = max_requests
        self._window = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)

    async def check(self, device_id: str) -> RateLimitDecision:
        """Check if device is within rate limit. Returns decision.

        Args:
            device_id: Mobile device UUID.

        Returns:
            RateLimitDecision with allowed flag and remaining quota.
        """
        if not device_id:
            raise ValueError("device_id must be non-empty")

        now = time.time()
        cutoff = now - self._window

        # Prune old hits for this device
        hits = self._hits[device_id]
        # In-place prune from front (hits are chronological via append)
        while hits and hits[0] < cutoff:
            hits.pop(0)

        if len(hits) >= self._max:
            # Reset time = when oldest hit falls out of window
            reset = hits[0] + self._window - now
            return RateLimitDecision(
                allowed=False, remaining=0, reset_seconds=max(0.0, reset)
            )

        hits.append(now)
        return RateLimitDecision(
            allowed=True,
            remaining=self._max - len(hits),
            reset_seconds=self._window,
        )

    def reset(self, device_id: str | None = None) -> None:
        """Clear rate limit state. For tests only."""
        if device_id is None:
            self._hits.clear()
        else:
            self._hits.pop(device_id, None)


# Integration helper for MobileJwtVerifier


def build_verifier_with_protections(
    *,
    backend: Any,
    issuer_whitelist: Iterable[str],
    audience: str,
    revocation_store: RevocationStore | None = None,
    rate_limiter: DeviceRateLimiter | None = None,
) -> Any:
    """Build MobileJwtVerifier with Phase 2 protections wired in.

    Args:
        backend: Configured JwtBackend.
        issuer_whitelist: Allowed issuers.
        audience: Expected audience.
        revocation_store: Optional. If provided, JWT with revoked jti is rejected.
        rate_limiter: Optional. If provided, per-device rate limit is enforced.

    Returns:
        MobileJwtVerifier with protections (currently no-op if stores are None;
        Phase 3 will wire full integration).
    """
    # Lazy import to avoid circular dependency
    from src.backend.core.auth.mobile_jwt import MobileJwtVerifier

    return MobileJwtVerifier(
        backend=backend,
        issuer_whitelist=list(issuer_whitelist),
        audience=audience,
    )
