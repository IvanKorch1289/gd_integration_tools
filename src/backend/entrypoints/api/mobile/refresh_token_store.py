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
        """Check if refresh token is valid (not revoked)."""
        ...

    async def issue(self, user_id: str, device_id: str, refresh_jti: str, ttl_seconds: int) -> None:
        """Issue new refresh token (add to valid set)."""
        ...

    async def revoke(self, user_id: str, device_id: str, refresh_jti: str) -> None:
        """Revoke a refresh token (remove from valid set)."""
        ...


class InMemoryRefreshTokenStore:
    """In-memory refresh token store (test/dev only).

    Storage: ``_tokens: set[(user_id, device_id, refresh_jti)]``.

    NOT for multi-pod production (use Redis-backed impl, future work).
    """

    def __init__(self) -> None:
        self._tokens: set[tuple[str, str, str]] = set()
        self._expiry: dict[tuple[str, str, str], float] = {}

    async def is_valid(self, user_id: str, device_id: str, refresh_jti: str) -> bool:
        key = (user_id, device_id, refresh_jti)
        if key not in self._tokens:
            return False
        # Auto-expire
        expires = self._expiry.get(key, float("inf"))
        if expires <= time.time():
            self._tokens.discard(key)
            self._expiry.pop(key, None)
            return False
        return True

    async def issue(self, user_id: str, device_id: str, refresh_jti: str, ttl_seconds: int) -> None:
        if not refresh_jti or not isinstance(refresh_jti, str):
            raise ValueError("refresh_jti must be non-empty string")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be > 0")
        key = (user_id, device_id, refresh_jti)
        self._tokens.add(key)
        self._expiry[key] = time.time() + ttl_seconds
        _logger.info(
            "refresh token issued: user=%s device=%s jti=%s ttl=%ds",
            user_id, device_id, refresh_jti[:8], ttl_seconds,
        )

    async def revoke(self, user_id: str, device_id: str, refresh_jti: str) -> None:
        key = (user_id, device_id, refresh_jti)
        self._tokens.discard(key)
        self._expiry.pop(key, None)
        _logger.info(
            "refresh token revoked: user=%s device=%s jti=%s",
            user_id, device_id, refresh_jti[:8],
        )

    def __len__(self) -> int:
        return len(self._tokens)


# Module-level singleton for demo mode (in-memory)
_default_store: InMemoryRefreshTokenStore | None = None


def get_refresh_token_store() -> InMemoryRefreshTokenStore:
    """Lazy singleton for refresh token store (in-memory)."""
    global _default_store
    if _default_store is None:
        _default_store = InMemoryRefreshTokenStore()
    return _default_store
