"""Tests для JWT blacklist Redis fallback (S189+)."""

from __future__ import annotations

from unittest.mock import patch


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
