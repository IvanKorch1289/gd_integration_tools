"""Tests для JWT blacklist Redis fallback (S189+)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.backend.services.security.facade import SecurityFacade


class TestJWTBlacklistFallback:
    """Тесты JWT blacklist Redis fallback (переписаны под async facade).

    История: старые sync-тесты (S189+) вызывали async-методы без await —
    не работали с момента появления async facade (B-NEW-3, 2026-09-05).
    """

    @pytest.mark.asyncio
    async def test_redis_blacklist_used_when_available(self) -> None:
        """Redis доступен -> RedisJwtBlacklist (multi-worker safe)."""
        facade = SecurityFacade()
        with (
            patch("src.backend.infrastructure.clients.storage.redis.get_redis_client") as mock_rc,
            patch("src.backend.core.auth.jwt_blacklist.RedisJwtBlacklist") as mock_cls,
        ):
            mock_rc.return_value.get_client = AsyncMock(return_value=object())
            await facade.init_jwt_blacklist()
            mock_cls.assert_called_once()
            assert facade._jwt_blacklist is mock_cls.return_value

    @pytest.mark.asyncio
    async def test_in_memory_fallback_when_redis_unavailable(self) -> None:
        """Redis недоступен -> InMemoryJwtBlacklist (single-process fallback)."""
        from src.backend.services.security.facade_blacklist import InMemoryJwtBlacklist

        facade = SecurityFacade()
        with patch(
            "src.backend.infrastructure.clients.storage.redis.get_redis_client",
            side_effect=RuntimeError("Redis down"),
        ):
            await facade.init_jwt_blacklist()
            assert isinstance(facade._jwt_blacklist, InMemoryJwtBlacklist)

    @pytest.mark.asyncio
    async def test_blacklist_token_with_redis(self) -> None:
        """blacklist_token добавляет через Redis-бэкенд."""
        facade = SecurityFacade()
        mock_blacklist = AsyncMock()
        mock_blacklist.revoke = AsyncMock()
        mock_blacklist.is_revoked = AsyncMock(return_value=True)
        with (
            patch("src.backend.infrastructure.clients.storage.redis.get_redis_client"),
            patch("src.backend.core.auth.jwt_blacklist.RedisJwtBlacklist"),
            patch.object(
                facade, "_jwt_blacklist", mock_blacklist, create=True
            ),
            patch.object(facade, "_jwt_blacklist_ready", True, create=True),
        ):
            assert await facade.blacklist_token("jti-test-1") is True
            mock_blacklist.revoke.assert_awaited_once()
            assert await facade.is_token_blacklisted("jti-test-1") is True

    @pytest.mark.asyncio
    async def test_blacklist_token_with_fallback(self) -> None:
        """blacklist_token работает с in-memory fallback (без Redis)."""
        facade = SecurityFacade()
        with patch(
            "src.backend.infrastructure.clients.storage.redis.get_redis_client",
            side_effect=RuntimeError("Redis down"),
        ):
            assert await facade.blacklist_token("jti-fallback-1") is True
            assert await facade.is_token_blacklisted("jti-fallback-1") is True

    @pytest.mark.asyncio
    async def test_unblacklist_token_with_fallback(self) -> None:
        """unblacklist_token удаляет токен (in-memory fallback)."""
        facade = SecurityFacade()
        with patch(
            "src.backend.infrastructure.clients.storage.redis.get_redis_client",
            side_effect=RuntimeError("Redis down"),
        ):
            await facade.blacklist_token("jti-1")
            assert await facade.is_token_blacklisted("jti-1") is True
            assert await facade.unblacklist_token("jti-1") is True
            assert await facade.is_token_blacklisted("jti-1") is False

    @pytest.mark.asyncio
    async def test_clear_blacklist_with_fallback(self) -> None:
        """clear_blacklist очищает in-memory blacklist."""
        facade = SecurityFacade()
        with patch(
            "src.backend.infrastructure.clients.storage.redis.get_redis_client",
            side_effect=RuntimeError("Redis down"),
        ):
            await facade.blacklist_token("jti-1")
            await facade.blacklist_token("jti-2")
            await facade.clear_blacklist()
            assert await facade.is_token_blacklisted("jti-1") is False
            assert await facade.is_token_blacklisted("jti-2") is False

    @pytest.mark.asyncio
    async def test_instances_independent(self) -> None:
        """Конструктор не кэшируется; каждый инстанс — своё состояние."""
        f1 = SecurityFacade()
        f2 = SecurityFacade()
        assert f1 is not f2

        with patch(
            "src.backend.infrastructure.clients.storage.redis.get_redis_client",
            side_effect=RuntimeError("Redis down"),
        ):
            await f1.blacklist_token("only-f1")
            assert await f1.is_token_blacklisted("only-f1") is True
            assert await f2.is_token_blacklisted("only-f1") is False


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
