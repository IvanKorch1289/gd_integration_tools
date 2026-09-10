"""Tests for DesktopRPASessionPool (PERF-6.6 Sprint 14 coverage ratchet).

Coverage target: desktop_session_pool.py 0% → 70%+.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.services.rpa.desktop_session_pool import (
    DesktopRPASessionPool,
    DesktopRPASessionStats,
    _PooledSession,
)


@pytest.fixture
def pool() -> DesktopRPASessionPool:
    """Pool instance with base_url only (no API key, fast timeout)."""
    return DesktopRPASessionPool(
        base_url="http://rpa-test:8080",
        timeout=1.0,
        ttl_seconds=60.0,
        max_sessions=4,
    )


def test_init_requires_base_url() -> None:
    """base_url пустая → ValueError."""
    with pytest.raises(ValueError, match="base_url обязателен"):
        DesktopRPASessionPool(base_url="")


def test_init_strips_trailing_slash() -> None:
    """base_url 'http://x/' нормализуется в 'http://x'."""
    p = DesktopRPASessionPool(base_url="http://example.com/")
    assert p._base_url == "http://example.com"


def test_init_stores_config() -> None:
    """Constructor сохраняет api_key, timeout, ttl, max_sessions."""
    p = DesktopRPASessionPool(
        base_url="http://x:1",
        api_key="secret",
        timeout=5.0,
        ttl_seconds=120.0,
        max_sessions=8,
    )
    assert p._api_key == "secret"
    assert p._timeout == 5.0
    assert p._ttl == 120.0
    assert p._max_sessions == 8


@pytest.mark.asyncio
async def test_acquire_yields_client(pool: DesktopRPASessionPool) -> None:
    """acquire() — async context manager, вызывает make_http_client."""
    with patch(
        "src.backend.services.rpa.desktop_session_pool.make_http_client"
    ) as mock_make:
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_make.return_value = mock_client

        async with pool.acquire("default") as client:
            assert client is mock_client
            assert mock_make.called


@pytest.mark.asyncio
async def test_acquire_reuses_existing_session(pool: DesktopRPASessionPool) -> None:
    """acquire() с одним app_name 2 раза — переиспользует session (no new client)."""
    with patch(
        "src.backend.services.rpa.desktop_session_pool.make_http_client"
    ) as mock_make:
        async with pool.acquire("default"):
            pass
        async with pool.acquire("default"):
            pass
        # _make_client called только 1 раз (reuse)
        assert mock_make.call_count == 1


@pytest.mark.asyncio
async def test_healthcheck_returns_bool(pool: DesktopRPASessionPool) -> None:
    """healthcheck возвращает bool (True или False)."""
    with patch(
        "src.backend.services.rpa.desktop_session_pool.make_http_client"
    ):
        async with pool.acquire("default"):
            pass
        result = await pool.healthcheck("default")
        assert isinstance(result, bool)


@pytest.mark.asyncio
async def test_healthcheck_false_when_no_session(
    pool: DesktopRPASessionPool,
) -> None:
    """healthcheck возвращает False если session не существует."""
    assert await pool.healthcheck("never_existed") is False


@pytest.mark.asyncio
async def test_reconnect_replaces_session(
    pool: DesktopRPASessionPool,
) -> None:
    """reconnect() сбрасывает cached session — следующий acquire создаст новый."""
    with patch(
        "src.backend.services.rpa.desktop_session_pool.make_http_client"
    ) as mock_make:
        async with pool.acquire("default"):
            pass
        await pool.reconnect("default")
        async with pool.acquire("default"):
            pass
        # После reconnect — _make_client вызван 2 раза (новый client)
        assert mock_make.call_count == 2


@pytest.mark.asyncio
async def test_stats_initial_state(pool: DesktopRPASessionPool) -> None:
    """stats() до acquire → 0 sessions."""
    stats = await pool.stats()
    assert stats.total == 0
    assert stats.in_use == 0
    assert stats.idle == 0


@pytest.mark.asyncio
async def test_stats_after_acquire(pool: DesktopRPASessionPool) -> None:
    """stats() после acquire → 1 total session."""
    with patch("src.backend.services.rpa.desktop_session_pool.make_http_client"):
        async with pool.acquire("app1"):
            pass
        async with pool.acquire("app1"):
            pass
        stats = await pool.stats()
        assert stats.total == 1
        # by_app tracks per-app state
        assert "app1" in stats.by_app


@pytest.mark.asyncio
async def test_shutdown_closes_all_clients(pool: DesktopRPASessionPool) -> None:
    """shutdown() очищает sessions."""
    with patch("src.backend.services.rpa.desktop_session_pool.make_http_client"):
        async with pool.acquire("app1"):
            pass
        async with pool.acquire("app2"):
            pass
        await pool.shutdown()
        stats = await pool.stats()
        assert stats.total == 0


@pytest.mark.asyncio
async def test_max_sessions_enforced(
    pool: DesktopRPASessionPool,
) -> None:
    """Если max_sessions превышен → старые sessions evicted."""
    with patch("src.backend.services.rpa.desktop_session_pool.make_http_client"):
        # pool.max_sessions = 4
        for i in range(5):
            async with pool.acquire(f"app{i}"):
                pass
        stats = await pool.stats()
        # 5 sessions tried, но max=4 → total ≤ 4
        assert stats.total <= 4


def test_get_set_desktop_rpa_pool_singleton() -> None:
    """get_desktop_rpa_pool/set_desktop_rpa_pool — DI singleton helpers."""
    from src.backend.services.rpa.desktop_session_pool import (
        get_desktop_rpa_pool,
        set_desktop_rpa_pool,
    )

    # Initial — None
    set_desktop_rpa_pool(None)
    assert get_desktop_rpa_pool() is None

    # Set custom pool
    custom = DesktopRPASessionPool(base_url="http://custom:1")
    set_desktop_rpa_pool(custom)
    assert get_desktop_rpa_pool() is custom

    # Reset
    set_desktop_rpa_pool(None)
    assert get_desktop_rpa_pool() is None
