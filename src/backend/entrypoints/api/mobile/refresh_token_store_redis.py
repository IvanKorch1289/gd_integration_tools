"""Redis-backed refresh token rotation store (S55 W2).

Multi-pod production implementation. Same Protocol as the in-memory
store (``refresh_token_store.py``), backed by Redis for cluster-wide
state consistency.

Key format: ``gd:mobile:refresh:<user_id>:<device_id>:<jti>``
Value: timestamp string (existence = token is valid)
TTL: configured per issuance

Atomicity: ``issue_if_new`` uses Redis ``SET key value NX EX ttl`` for
single-op first-use detection (no race condition across pods).

Fail-CLOSED on Redis errors: if Redis is unavailable, ``is_valid`` /
``issue_if_new`` return False (caller treats as invalid/missing token).
For demo / single-pod fallback, the in-memory store is used instead
via ``get_refresh_token_store()`` factory selection.

Production deployment:
- ENABLE Redis: set ``REDIS_ENABLED=true`` and ``REDIS_URL=redis://...``
- Multi-pod: each pod shares Redis state, so rotation is cluster-wide.
- Single-pod: same store works (no cluster semantics).
"""

from __future__ import annotations

from typing import Any

from src.backend.core.logging import get_logger

_logger = get_logger(__name__)


class RedisRefreshTokenStore:
    """Redis-backed implementation of RefreshTokenStore Protocol.

    Multi-pod production grade. Single source of truth for rotation
    state across all application pods.

    Args:
        key_prefix: Redis key prefix (default: ``gd:mobile:refresh:``).
            Allows namespacing per environment / tenant.

    """

    def __init__(self, *, key_prefix: str = "gd:mobile:refresh:") -> None:
        """Initialize Redis-backed store.

        Args:
            key_prefix: Redis key prefix for namespacing.

        """
        self._prefix = key_prefix

    def _key(self, user_id: str, device_id: str, refresh_jti: str) -> str:
        """Build Redis key for the given token."""
        return f"{self._prefix}{user_id}:{device_id}:{refresh_jti}"

    def _generation_key(self, user_id: str, device_id: str) -> str:
        """Redis key for generation counter (used by revoke_family)."""
        return f"{self._prefix}gen:{user_id}:{device_id}"

    async def _get_client(self) -> Any:
        """Lazy-fetch Redis client. Returns None if Redis unavailable.

        ``get_redis_client()`` is sync (returns RedisClient directly).
        """
        try:
            from src.backend.core.storage.redis import get_redis_client

            return get_redis_client()
        except Exception as exc:
            _logger.warning(
                "redis refresh store: client unavailable: %s", exc
            )
            return None

    async def _get_generation(self, client: Any, user_id: str, device_id: str) -> int:
        """Read current generation counter for (user, device)."""
        try:
            raw = await client.cache_get(self._generation_key(user_id, device_id))
            return int(raw) if raw else 0
        except Exception:
            return 0

    async def is_valid(
        self, user_id: str, device_id: str, refresh_jti: str
    ) -> bool:
        """Check if refresh token is valid (key exists AND current generation).

        S56 W1: family revocation check — token must be at CURRENT
        generation for (user, device). After ``revoke_family`` bumps
        generation, old tokens fail this check even if their keys exist.

        Fail-CLOSED on Redis errors: returns False when Redis unavailable
        or query fails.

        Args:
            user_id: User identifier.
            device_id: Device identifier.
            refresh_jti: JWT jti or refresh token jti.

        Returns:
            True if token key exists AND at current generation; False otherwise.

        """
        client = await self._get_client()
        if client is None:
            return False  # fail-CLOSED
        try:
            # Check key exists
            value = await client.cache_get(
                self._key(user_id, device_id, refresh_jti)
            )
            if value is None:
                return False
            # Check generation matches (family revocation gate)
            current_gen = await self._get_generation(client, user_id, device_id)
            # Token key value contains generation (set by issue)
            try:
                token_gen = int(value)
            except (ValueError, TypeError):
                return False
            return token_gen == current_gen
        except Exception as exc:
            _logger.warning(
                "redis refresh is_valid error: user=%s err=%s", user_id, exc
            )
            return False  # fail-CLOSED

    async def issue(
        self,
        user_id: str,
        device_id: str,
        refresh_jti: str,
        ttl_seconds: int,
    ) -> None:
        """Issue new refresh token at current generation (SET with TTL).

        Value format: generation number (used by is_valid for family check).
        For multi-pod race-free first-use detection, prefer
        ``issue_if_new()`` instead.

        Args:
            user_id: User identifier.
            device_id: Device identifier.
            refresh_jti: JWT jti or refresh token jti.
            ttl_seconds: Time-to-live in seconds.

        Raises:
            ValueError: on invalid args.

        """
        if not refresh_jti or not isinstance(refresh_jti, str):
            raise ValueError("refresh_jti must be non-empty string")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be > 0")

        client = await self._get_client()
        if client is None:
            _logger.warning(
                "redis refresh issue: client unavailable, jti=%s not persisted",
                refresh_jti,
            )
            return

        try:
            current_gen = await self._get_generation(client, user_id, device_id)
            await client.cache_set(
                self._key(user_id, device_id, refresh_jti),
                str(current_gen),
                expire=ttl_seconds,
            )
            _logger.info(
                "redis refresh issued: user=%s device=%s jti=%s gen=%d ttl=%ds",
                user_id,
                device_id,
                refresh_jti[:8],
                current_gen,
                ttl_seconds,
            )
        except Exception as exc:
            _logger.error(
                "redis refresh issue failed: user=%s jti=%s err=%s",
                user_id,
                refresh_jti[:8],
                exc,
            )
            raise

    async def issue_if_new(
        self,
        user_id: str,
        device_id: str,
        refresh_jti: str,
        ttl_seconds: int,
    ) -> bool:
        """Atomically issue token ONLY if not already present (current gen).

        Uses Redis ``SET key value NX EX ttl`` — single atomic op.
        Value includes current generation for family revocation check.
        Returns ``True`` if newly set (first-use), ``False`` if key
        already existed (reuse detected).

        Cross-pod atomicity: this is the SAFE operation for JWT path
        rotation where multiple pods may receive concurrent requests
        with the same JWT jti.

        Args:
            user_id: User identifier.
            device_id: Device identifier.
            refresh_jti: JWT jti or refresh token jti.
            ttl_seconds: Time-to-live in seconds.

        Returns:
            True if newly issued; False if key already existed (reuse)
            OR Redis unavailable (fail-CLOSED).

        Raises:
            ValueError: on invalid args.

        """
        if not refresh_jti or not isinstance(refresh_jti, str):
            raise ValueError("refresh_jti must be non-empty string")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be > 0")

        client = await self._get_client()
        if client is None:
            return False  # fail-CLOSED

        key = self._key(user_id, device_id, refresh_jti)
        try:
            current_gen = await self._get_generation(client, user_id, device_id)
            # Atomic SET NX EX with generation as value
            result = await client.execute(
                "cache",
                lambda conn: conn.set(key, str(current_gen), nx=True, ex=ttl_seconds),
            )
            newly_issued = bool(result)
            _logger.info(
                "redis refresh issue_if_new: user=%s jti=%s gen=%d newly_issued=%s",
                user_id,
                refresh_jti[:8],
                current_gen,
                newly_issued,
            )
            return newly_issued
        except Exception as exc:
            _logger.warning(
                "redis refresh issue_if_new error: user=%s jti=%s err=%s",
                user_id,
                refresh_jti[:8],
                exc,
            )
            return False  # fail-CLOSED

    async def revoke(
        self, user_id: str, device_id: str, refresh_jti: str
    ) -> None:
        """Revoke a refresh token (delete Redis key).

        Args:
            user_id: User identifier.
            device_id: Device identifier.
            refresh_jti: JWT jti or refresh token jti.

        """
        client = await self._get_client()
        if client is None:
            _logger.warning(
                "redis refresh revoke: client unavailable, jti=%s not removed",
                refresh_jti,
            )
            return
        try:
            await client.cache_delete(
                self._key(user_id, device_id, refresh_jti)
            )
            _logger.info(
                "redis refresh revoked: user=%s device=%s jti=%s",
                user_id,
                device_id,
                refresh_jti[:8],
            )
        except Exception as exc:
            _logger.error(
                "redis refresh revoke failed: user=%s jti=%s err=%s",
                user_id,
                refresh_jti[:8],
                exc,
            )
            raise

    async def revoke_family(self, user_id: str, device_id: str) -> int:
        """Revoke entire token family: bump generation counter.

        S56 W1: OWASP family revocation. Bumps the generation counter
        for (user_id, device_id), invalidating all tokens at the old
        generation. Implementation:
        1. INCR generation counter (atomic Redis op)
        2. Use SCAN + DEL to remove all old-gen token keys
        3. Return count invalidated

        Cross-pod atomicity: INCR is single atomic Redis op.

        Args:
            user_id: User identifier.
            device_id: Device identifier.

        Returns:
            Number of tokens invalidated (for audit logging).
            Returns 0 on Redis errors (fail-CLOSED for security audit).

        """
        gen_key = self._generation_key(user_id, device_id)
        jti_prefix = self._prefix + f"{user_id}:{device_id}:"

        client = await self._get_client()
        if client is None:
            _logger.warning(
                "redis refresh revoke_family: client unavailable, "
                "user=%s device=%s not persisted",
                user_id,
                device_id,
            )
            return 0

        try:
            # Atomic INCR for generation counter
            new_gen = await client.execute(
                "cache",
                lambda conn: conn.incr(gen_key),
            )
            new_gen = int(new_gen) if new_gen else 1

            # SCAN + DEL old generation keys (best-effort cleanup)
            # Note: in high-traffic systems, a Lua script would be more efficient.
            removed = 0
            try:
                # Use raw execute with scan_iter for async iteration
                async for key in self._scan_prefix(client, jti_prefix):
                    await client.cache_delete(key)
                    removed += 1
            except Exception as scan_exc:
                _logger.warning(
                    "redis revoke_family scan cleanup error: %s", scan_exc
                )
                # Generation bump succeeded; old tokens will fail is_valid
                # anyway because of generation mismatch. Cleanup is best-effort.

            _logger.warning(
                "redis refresh family revoked: user=%s device=%s new_gen=%d "
                "tokens_cleaned=%d",
                user_id,
                device_id,
                new_gen,
                removed,
            )
            return removed
        except Exception as exc:
            _logger.error(
                "redis refresh revoke_family failed: user=%s err=%s",
                user_id,
                exc,
            )
            return 0

    async def _scan_prefix(self, client: Any, prefix: str) -> Any:
        """Async-iterate keys matching prefix. Yields key strings.

        Best-effort cleanup. Returns empty if SCAN fails (real Redis
        or mocked). The caller treats 0-removed as acceptable since
        generation bump already invalidates tokens via is_valid.
        """
        try:
            result = await client.execute(
                "cache",
                lambda conn: conn.scan_iter(match=f"{prefix}*", count=100),
            )
            if result is None:
                return
            async for key in result:
                # scan_iter returns bytes; decode to str
                if isinstance(key, bytes):
                    yield key.decode("utf-8")
                else:
                    yield key
        except Exception:
            # scan_iter unavailable (e.g., in mock) — silent no-op
            return

    async def cleanup_expired(self) -> int:
        """TTL handles cleanup automatically. Returns 0 (no-op for Redis)."""
        # Redis TTL auto-removes keys; explicit cleanup is unnecessary.
        return 0
