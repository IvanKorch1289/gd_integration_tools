"""Sprint 21 W6 — DesktopRPASessionPool tests (F-12 + B-09 closure).

Покрытие:
    * acquire/release lifecycle + session affinity по app_name.
    * Reconnect на ConnectError — session удаляется и пересоздаётся.
    * TTL expiry — idle session > ttl_seconds → recreate.
    * Stats отражает текущее состояние.
    * Shutdown закрывает все clients.
"""

from __future__ import annotations

import httpx
import pytest

from src.backend.services.rpa.desktop_session_pool import (
    DesktopRPASessionPool,
    get_desktop_rpa_pool,
    set_desktop_rpa_pool,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_pool() -> None:
    set_desktop_rpa_pool(None)
    yield
    set_desktop_rpa_pool(None)


@pytest.fixture
def pool() -> DesktopRPASessionPool:
    return DesktopRPASessionPool(
        base_url="http://worker.local:9001",
        api_key=None,
        timeout=10.0,
        ttl_seconds=60.0,
        max_sessions=4,
    )


async def test_invalid_base_url() -> None:
    with pytest.raises(ValueError):
        DesktopRPASessionPool(base_url="")


async def test_acquire_creates_session(pool: DesktopRPASessionPool) -> None:
    """Первый acquire создаёт session по app_name."""
    async with pool.acquire("notepad") as client:
        assert isinstance(client, httpx.AsyncClient)
    stats = await pool.stats()
    assert stats.total == 1
    assert stats.idle == 1
    assert "notepad" in stats.by_app
    await pool.shutdown()


async def test_session_affinity_same_client(pool: DesktopRPASessionPool) -> None:
    """Повторный acquire того же app_name возвращает тот же client."""
    async with pool.acquire("calc") as client1:
        pass
    async with pool.acquire("calc") as client2:
        pass
    assert client1 is client2
    await pool.shutdown()


async def test_different_apps_different_clients(pool: DesktopRPASessionPool) -> None:
    """Разные app_name → разные clients."""
    async with pool.acquire("notepad") as c1:
        pass
    async with pool.acquire("calc") as c2:
        pass
    assert c1 is not c2
    stats = await pool.stats()
    assert stats.total == 2
    await pool.shutdown()


async def test_reconnect_on_stale_handle(pool: DesktopRPASessionPool) -> None:
    """ConnectError внутри acquire-блока — session удалена для reconnect."""
    with pytest.raises(httpx.ConnectError):
        async with pool.acquire("notepad") as client:
            # Симулируем stale handle
            raise httpx.ConnectError("connection refused")

    stats = await pool.stats()
    assert stats.total == 0  # session удалена
    # Следующий acquire создаёт fresh client
    async with pool.acquire("notepad") as new_client:
        assert isinstance(new_client, httpx.AsyncClient)
    await pool.shutdown()


async def test_ttl_expiry_recreates_session() -> None:
    """Idle session старше TTL → recreate на next acquire."""
    pool = DesktopRPASessionPool(
        base_url="http://worker:9001",
        ttl_seconds=0.001,  # 1ms — для быстрого теста
        max_sessions=2,
    )
    async with pool.acquire("app") as c1:
        pass
    # Ждём TTL
    import asyncio

    await asyncio.sleep(0.01)
    async with pool.acquire("app") as c2:
        pass
    assert c1 is not c2
    await pool.shutdown()


async def test_max_sessions_evicts_oldest_idle() -> None:
    """При достижении max_sessions выбрасывается самый старый idle session."""
    pool = DesktopRPASessionPool(
        base_url="http://worker:9001", ttl_seconds=3600.0, max_sessions=2
    )
    async with pool.acquire("app_a") as _ca:
        pass
    async with pool.acquire("app_b") as _cb:
        pass
    stats = await pool.stats()
    assert stats.total == 2

    # Третий запрос вытеснит самый старый idle (app_a)
    async with pool.acquire("app_c") as _cc:
        pass
    stats = await pool.stats()
    assert stats.total == 2
    assert "app_c" in stats.by_app
    await pool.shutdown()


async def test_force_reconnect(pool: DesktopRPASessionPool) -> None:
    """Принудительный reconnect удаляет session."""
    async with pool.acquire("notepad") as _c:
        pass
    await pool.reconnect("notepad")
    stats = await pool.stats()
    assert stats.total == 0
    await pool.shutdown()


async def test_singleton_get_set() -> None:
    """Module-level singleton API."""
    assert get_desktop_rpa_pool() is None
    p = DesktopRPASessionPool(base_url="http://w:9001")
    set_desktop_rpa_pool(p)
    assert get_desktop_rpa_pool() is p
    set_desktop_rpa_pool(None)
    assert get_desktop_rpa_pool() is None
    await p.shutdown()


async def test_warm_5_sessions(pool: DesktopRPASessionPool) -> None:
    """Pool warm 5 sessions при пяти разных app_name."""
    # Override max_sessions для теста
    pool._max_sessions = 5
    for app in ["a", "b", "c", "d", "e"]:
        async with pool.acquire(app) as _c:
            pass
    stats = await pool.stats()
    assert stats.total == 5
    await pool.shutdown()
