"""Refresh token rotation store (S52 W3).

Per ADR-0267 (S52 plan): mobile JWT refresh endpoint should rotate
refresh tokens — when issuing a new pair, revoke the old refresh token
to prevent reuse attacks.

Provides:
- ``RefreshTokenStore`` Protocol
- ``InMemoryRefreshTokenStore`` implementation (test/dev)
- Integration with existing ``RevocationStore`` from S47 W1

Phase 2c (S51 W2) ships the foundation; Phase 3 (S52 W3) implements rotation.

Why rotation matters (OWASP):
- Stolen refresh tokens can be reused for full token lifetime
- Rotation limits attack window: attacker must use stolen token BEFORE
  legitimate user refreshes (window = refresh interval, not lifetime)
- Detects theft: if legitimate user rotates and attacker tries to use
  old token, server detects reuse and revokes entire token family

This module is the minimal "track which refresh tokens are valid" piece.
Full rotation logic (JWT path) is in the refresh endpoint itself.
"""

from __future__ import annotations

import time
from typing import Protocol

from src.backend.core.logging import get_logger

_logger = get_logger(__name__)


class RefreshTokenStore(Protocol):
    """Protocol for refresh token rotation tracking.

    Tracks issued refresh tokens per (user_id, device_id) pair. Each
    refresh operation:
    1. Verifies old refresh token is valid (in issued set)
    2. Issues new refresh token
    3. Marks old refresh token as revoked
    """

    async def is_valid(self, user_id: str, device_id: str, refresh_jti: str) -> bool:
        """Check if refresh token is valid (not revoked, current generation)."""
        ...

    async def issue(self, user_id: str, device_id: str, refresh_jti: str, ttl_seconds: int) -> None:
        """Issue new refresh token (add to valid set at current generation)."""
        ...

    async def revoke(self, user_id: str, device_id: str, refresh_jti: str) -> None:
        """Revoke a refresh token (remove from valid set)."""
        ...

    async def issue_if_new(
        self, user_id: str, device_id: str, refresh_jti: str, ttl_seconds: int
    ) -> bool:
        """Atomically issue token ONLY if not already present.

        Returns ``True`` if newly issued, ``False`` if key already existed
        (reuse detected). Used for JWT-mode rotation where the jti is
        foreign (from external auth provider) and we need to detect
        first-use vs. reuse within a single atomic operation.
        """
        ...

    async def revoke_family(self, user_id: str, device_id: str) -> int:
        """Revoke entire token family for (user_id, device_id).

        Implements OWASP ASVS V3.5 family revocation: when reuse is
        detected, ALL tokens currently issued for this user+device
        pair are invalidated. User must re-authenticate (full re-login)
        to obtain fresh tokens.

        Returns:
            Number of tokens invalidated (for audit logging).

        """
        ...


class InMemoryRefreshTokenStore:
    """In-memory refresh token store (test/dev only).

    Storage:
    - ``_tokens: dict[(user_id, device_id, jti), (generation, expiry)]``
    - ``_generations: dict[(user_id, device_id), int]``

    S56 W1: Per-(user, device) generation counter enables family
    revocation — when reuse is detected, bump generation to invalidate
    all current-generation tokens for that pair.

    NOT for multi-pod production — use ``RedisRefreshTokenStore``
    from ``refresh_token_store_redis`` for cluster-wide state.
    """

    def __init__(self) -> None:
        # key: (user_id, device_id, jti), value: (generation, expiry)
        self._tokens: dict[tuple[str, str, str], tuple[int, float]] = {}
        # per (user, device) current generation counter
        self._generations: dict[tuple[str, str], int] = {}

    def _current_generation(self, user_id: str, device_id: str) -> int:
        """Get current generation for (user, device) pair (default 0)."""
        return self._generations.get((user_id, device_id), 0)

    async def is_valid(self, user_id: str, device_id: str, refresh_jti: str) -> bool:
        key = (user_id, device_id, refresh_jti)
        if key not in self._tokens:
            return False
        gen, expires = self._tokens[key]
        # Auto-expire
        if expires <= time.time():
            self._tokens.pop(key, None)
            return False
        # Family check: only current generation is valid
        current_gen = self._current_generation(user_id, device_id)
        return gen == current_gen

    async def issue(self, user_id: str, device_id: str, refresh_jti: str, ttl_seconds: int) -> None:
        if not refresh_jti or not isinstance(refresh_jti, str):
            raise ValueError("refresh_jti must be non-empty string")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be > 0")
        key = (user_id, device_id, refresh_jti)
        gen = self._current_generation(user_id, device_id)
        self._tokens[key] = (gen, time.time() + ttl_seconds)
        _logger.info(
            "refresh token issued: user=%s device=%s jti=%s gen=%d ttl=%ds",
            user_id, device_id, refresh_jti[:8], gen, ttl_seconds,
        )

    async def issue_if_new(
        self, user_id: str, device_id: str, refresh_jti: str, ttl_seconds: int
    ) -> bool:
        """Atomically issue token ONLY if not already present.

        Returns ``True`` if newly issued (first-use), ``False`` if key
        already existed (reuse detected). Atomicity guarantee:
        in-memory dict assignment is thread-safe under GIL
        (asyncio single-thread); for multi-pod Redis impl, would need
        Lua script.

        Args:
            user_id: User identifier.
            device_id: Device identifier.
            refresh_jti: JWT jti (foreign from external auth provider in JWT mode).
            ttl_seconds: Time-to-live in seconds.

        Returns:
            True if newly issued; False if key already existed at current gen.

        Raises:
            ValueError: on invalid args (same as ``issue()``).

        """
        if not refresh_jti or not isinstance(refresh_jti, str):
            raise ValueError("refresh_jti must be non-empty string")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be > 0")
        key = (user_id, device_id, refresh_jti)
        current_gen = self._current_generation(user_id, device_id)
        if key in self._tokens:
            existing_gen, expires = self._tokens[key]
            # Only count as reuse if same generation AND not expired
            if existing_gen == current_gen and expires > time.time():
                return False  # reuse detected
            # Expired or stale gen — fall through to re-issue
            self._tokens.pop(key, None)
        # First-use: add to dict
        self._tokens[key] = (current_gen, time.time() + ttl_seconds)
        _logger.info(
            "refresh token issued (first-use): user=%s device=%s jti=%s gen=%d ttl=%ds",
            user_id, device_id, refresh_jti[:8], current_gen, ttl_seconds,
        )
        return True

    async def revoke(self, user_id: str, device_id: str, refresh_jti: str) -> None:
        key = (user_id, device_id, refresh_jti)
        self._tokens.pop(key, None)
        _logger.info(
            "refresh token revoked: user=%s device=%s jti=%s",
            user_id, device_id, refresh_jti[:8],
        )

    async def revoke_family(self, user_id: str, device_id: str) -> int:
        """Revoke entire token family for (user_id, device_id).

        Implements OWASP ASVS V3.5 family revocation: bumps generation
        counter, invalidating ALL tokens at the current generation.
        New tokens issued after this will use the next generation.

        Returns:
            Number of tokens invalidated (for audit logging).

        """
        key = (user_id, device_id)
        old_gen = self._generations.get(key, 0)
        new_gen = old_gen + 1
        self._generations[key] = new_gen
        # Count + remove tokens at old generation
        to_remove = [
            tkey
            for tkey, (gen, _exp) in self._tokens.items()
            if tkey[0] == user_id and tkey[1] == device_id and gen == old_gen
        ]
        for tkey in to_remove:
            self._tokens.pop(tkey, None)
        _logger.warning(
            "refresh token family revoked: user=%s device=%s old_gen=%d new_gen=%d "
            "tokens_invalidated=%d",
            user_id, device_id, old_gen, new_gen, len(to_remove),
        )
        return len(to_remove)

    def __len__(self) -> int:
        return len(self._tokens)


# Module-level singleton for demo mode (in-memory)
_default_store: InMemoryRefreshTokenStore | None = None


def get_refresh_token_store() -> RefreshTokenStore:
    """Lazy singleton for refresh token store.

    S55 W2: factory selects Redis-backed impl when ``REDIS_ENABLED=true``
    in environment, otherwise returns in-memory store (single-pod dev/test).
    Both impls satisfy the same Protocol interface, so callers don't need
    to know which one is in use.

    Returns:
        ``InMemoryRefreshTokenStore`` (default, dev/test) or
        ``RedisRefreshTokenStore`` (production multi-pod).

    """
    global _default_store
    if _default_store is None:
        import os

        if os.environ.get("REDIS_ENABLED", "").lower() == "true":
            # Lazy import to avoid hard dep on Redis client at module-load time
            from src.backend.entrypoints.api.mobile.refresh_token_store_redis import (
                RedisRefreshTokenStore,
            )

            _default_store = RedisRefreshTokenStore()
        else:
            _default_store = InMemoryRefreshTokenStore()
    return _default_store
