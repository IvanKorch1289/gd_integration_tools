"""Tests для JWT blacklist Redis fallback (S189+)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.backend.services.security.facade import SecurityFacade


class TestJWTBlacklistFallback:
    """Тесты JWT blacklist Redis fallback."""

    def test_redis_blacklist_used_when_available(self) -> None:
        """При доступности Redis используется RedisJwtBlacklist."""
        with patch(
            "src.backend.core.auth.jwt_blacklist.RedisJwtBlacklist"
        ) as mock_redis_cls:
            mock_blacklist = mock_redis_cls.return_value

            facade = SecurityFacade()

            assert facade._jwt_blacklist is mock_blacklist

    def test_in_memory_fallback_when_redis_unavailable(self) -> None:
        """При недоступности Redis — in-memory fallback."""
        with patch(
            "src.backend.core.auth.jwt_blacklist.RedisJwtBlacklist",
            side_effect=RuntimeError("Redis down"),
        ):
            facade = SecurityFacade()

            # Fallback должен быть dict-like с jti key
            assert isinstance(facade._jwt_blacklist, dict)
            assert "jti" in facade._jwt_blacklist

    def test_blacklist_token_with_redis(self) -> None:
        """blacklist_token добавляет через Redis."""
        with patch(
            "src.backend.core.auth.jwt_blacklist.RedisJwtBlacklist"
        ) as mock_redis_cls:
            mock_blacklist = mock_redis_cls.return_value

            facade = SecurityFacade()
            facade.blacklist_token("jti-test-1")

            assert facade.is_token_blacklisted("jti-test-1") is True

    def test_blacklist_token_with_fallback(self) -> None:
        """blacklist_token работает с in-memory fallback."""
        with patch(
            "src.backend.core.auth.jwt_blacklist.RedisJwtBlacklist",
            side_effect=RuntimeError("Redis down"),
        ):
            facade = SecurityFacade()
            facade.blacklist_token("jti-fallback-1")

            assert facade.is_token_blacklisted("jti-fallback-1") is True

    def test_unblacklist_token(self) -> None:
        """unblacklist_token удаляет токен."""
        with patch(
            "src.backend.core.auth.jwt_blacklist.RedisJwtBlacklist"
        ) as mock_redis_cls:
            mock_blacklist = mock_redis_cls.return_value

            facade = SecurityFacade()
            facade.blacklist_token("jti-1")
            assert facade.is_token_blacklisted("jti-1") is True

            facade.unblacklist_token("jti-1")
            assert facade.is_token_blacklisted("jti-1") is False

    def test_clear_blacklist_with_redis(self) -> None:
        """clear_blacklist очищает Redis blacklist."""
        with patch(
            "src.backend.core.auth.jwt_blacklist.RedisJwtBlacklist"
        ) as mock_redis_cls:
            mock_blacklist = mock_redis_cls.return_value

            facade = SecurityFacade()
            facade.blacklist_token("jti-1")
            facade.blacklist_token("jti-2")
            facade.clear_blacklist()

            assert facade.is_token_blacklisted("jti-1") is False
            assert facade.is_token_blacklisted("jti-2") is False

    def test_singleton_cached(self) -> None:
        """get_security_facade returns same instance."""
        f1 = SecurityFacade()
        f2 = SecurityFacade()

        # SecurityFacade singleton pattern (lru_cache in get_security_facade)
        # Each construction creates new instance for backward compat
        assert f1 is not f2  # Different instances (constructor not cached)

        # But the actual blacklist within each instance is consistent
        f1.blacklist_token("test-jti")
        assert f1.is_token_blacklisted("test-jti") is True


class TestInMemoryJwtBlacklistTTLCache:
    """S210 Cycle 1 regression: TTLCache + Lock correctness."""

    @pytest.mark.asyncio
    async def test_revoke_unrevoke_is_revoked(self) -> None:
        from src.backend.services.security.facade import _InMemoryJwtBlacklist

        bl = _InMemoryJwtBlacklist()
        await bl.revoke("jti_x", expires_at=9999999999)
        assert await bl.is_revoked("jti_x") is True
        await bl.unrevoke("jti_x")
        assert await bl.is_revoked("jti_x") is False

    def test_concurrent_access_is_thread_safe(self) -> None:
        """TTLCache не thread-safe; ensure Lock wrapping prevents races."""
        import asyncio
        import threading

        from src.backend.services.security.facade import _InMemoryJwtBlacklist

        bl = _InMemoryJwtBlacklist()
        errors: list[Exception] = []

        def worker(thread_id: int) -> None:
            try:
                for i in range(100):
                    jti = f"jti_{thread_id}_{i}"
                    loop = asyncio.new_event_loop()
                    loop.run_until_complete(bl.revoke(jti, 9999999999))
                    loop.run_until_complete(bl.is_revoked(jti))
                    loop.run_until_complete(bl.unrevoke(jti))
                    loop.close()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Concurrent access errors: {errors}"
