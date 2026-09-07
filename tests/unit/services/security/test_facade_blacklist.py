"""Тесты JwtBlacklistMixin (S3 сплит, T3 ratchet: facade_blacklist 71%→≥90%).

Redis-ветка (через MagicMock(spec=RedisJwtBlacklist) для isinstance),
fallback-ветка InMemoryJwtBlacklist, no-op методы, идемпотентный init,
swallow-семантика ошибок.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.core.auth.jwt_blacklist import RedisJwtBlacklist
from src.backend.services.security.facade import SecurityFacade
from src.backend.services.security.facade_blacklist import InMemoryJwtBlacklist


def _facade_with_blacklist(blacklist: object, *, ready: bool = True) -> SecurityFacade:
    """Facade с подменённым blacklist-стором (без обращения к Redis)."""
    facade = SecurityFacade()
    facade._jwt_blacklist = blacklist  # type: ignore[attr-defined]
    facade._jwt_blacklist_ready = ready  # type: ignore[attr-defined]
    return facade


def _redis_like_mock() -> MagicMock:
    """Mock, проходящий isinstance(self._jwt_blacklist, RedisJwtBlacklist)."""
    mock = MagicMock(spec=RedisJwtBlacklist)
    mock._redis = AsyncMock()
    mock._key = MagicMock(side_effect=lambda jti: f"bl:{jti}")
    mock._prefix = "bl:"
    return mock


# ── no-op методы in-memory fallback ─────────────────────────────────


@pytest.mark.asyncio
async def test_is_iat_revoked_noop_returns_false() -> None:
    bl = InMemoryJwtBlacklist()
    assert await bl.is_iat_revoked(None) is False
    assert await bl.is_iat_revoked(1700000000) is False


@pytest.mark.asyncio
async def test_revoke_before_time_noop() -> None:
    bl = InMemoryJwtBlacklist()
    await bl.revoke_before_time(1700000000)  # не бросает
    assert await bl.is_revoked("anything") is False


# ── init_jwt_blacklist ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_jwt_blacklist_idempotent() -> None:
    """Повторный init не пересоздаёт store (ready-флаг)."""
    facade = SecurityFacade()
    with patch.object(
        facade,
        "_create_jwt_blacklist",
        new=AsyncMock(return_value=object()),
    ) as mock_create:
        await facade.init_jwt_blacklist()
        await facade.init_jwt_blacklist()
        mock_create.assert_awaited_once()


# ── blacklist_token ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_blacklist_token_success_returns_true() -> None:
    mock_blacklist = AsyncMock()
    facade = _facade_with_blacklist(mock_blacklist)
    assert await facade.blacklist_token("jti-1") is True
    mock_blacklist.revoke.assert_awaited_once()
    _, kwargs_or_args = mock_blacklist.revoke.await_args
    jti_arg = mock_blacklist.revoke.await_args.args[0]
    exp_arg = mock_blacklist.revoke.await_args.args[1]
    assert jti_arg == "jti-1"
    # default TTL 24h
    import time

    assert abs(exp_arg - (int(time.time()) + 86400)) < 5


@pytest.mark.asyncio
async def test_blacklist_token_revoke_failure_returns_false() -> None:
    mock_blacklist = AsyncMock()
    mock_blacklist.revoke = AsyncMock(side_effect=RuntimeError("redis write fail"))
    facade = _facade_with_blacklist(mock_blacklist)
    assert await facade.blacklist_token("jti-1") is False


# ── unblacklist_token ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unblacklist_redis_branch_deletes_key() -> None:
    redis_like = _redis_like_mock()
    redis_like._redis.delete = AsyncMock()
    facade = _facade_with_blacklist(redis_like)
    assert await facade.unblacklist_token("jti-1") is True
    redis_like._redis.delete.assert_awaited_once_with("bl:jti-1")


@pytest.mark.asyncio
async def test_unblacklist_failure_returns_false() -> None:
    mock_blacklist = AsyncMock()
    mock_blacklist.unrevoke = AsyncMock(side_effect=RuntimeError("del fail"))
    facade = _facade_with_blacklist(mock_blacklist)
    assert await facade.unblacklist_token("jti-1") is False


# ── clear_blacklist ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_clear_blacklist_redis_scan_pagination() -> None:
    """Scan-цикл: две страницы (cursor 5 -> 0), delete по ключам страниц."""
    redis_like = _redis_like_mock()
    redis_like._redis.scan = AsyncMock(
        side_effect=[(5, [b"bl:a", b"bl:b"]), (0, [])]
    )
    facade = _facade_with_blacklist(redis_like)
    await facade.clear_blacklist()
    redis_like._redis.delete.assert_any_await(b"bl:a", b"bl:b")


@pytest.mark.asyncio
async def test_clear_blacklist_in_memory_branch() -> None:
    bl = InMemoryJwtBlacklist()
    await bl.revoke("jti-1", expires_at=9999999999)
    facade = _facade_with_blacklist(bl)
    await facade.clear_blacklist()
    assert await bl.is_revoked("jti-1") is False


@pytest.mark.asyncio
async def test_clear_blacklist_none_noop() -> None:
    facade = SecurityFacade()
    facade._jwt_blacklist = None  # type: ignore[attr-defined]
    await facade.clear_blacklist()  # не бросает


# ── Redis-ветка с РЕАЛЬНЫМ RedisJwtBlacklist (isinstance-проверка) ──


@pytest.mark.asyncio
async def test_unblacklist_real_redis_instance_deletes_key() -> None:
    """isinstance-ветка: реальный RedisJwtBlacklist -> _redis.delete(_key(jti))."""
    redis_mock = AsyncMock()
    redis_mock.delete = AsyncMock()
    real_blacklist = RedisJwtBlacklist(redis_mock)
    facade = _facade_with_blacklist(real_blacklist)
    assert await facade.unblacklist_token("jti-9") is True
    redis_mock.delete.assert_awaited_once_with("blacklist:jwt:jti-9")


@pytest.mark.asyncio
async def test_clear_blacklist_swallows_backend_error() -> None:
    """Сбой clear-бэкенда глотается с warning (207-208), не бросает."""
    mock_blacklist = AsyncMock()
    mock_blacklist.clear = AsyncMock(side_effect=RuntimeError("clear fail"))
    facade = _facade_with_blacklist(mock_blacklist)
    await facade.clear_blacklist()  # не бросает
    mock_blacklist.clear.assert_awaited_once()
