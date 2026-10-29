"""ADR-0393 — desktop-RPA session pool: лимит сессий и активные пользователи.

Закрывает дефект волны 18 «(12) ``max_sessions`` не enforced + eviction
закрывает клиент под активным пользователем»:

* проба аудита: ``total=3`` при ``max_sessions=2`` (лимит не соблюдался);
* проба аудита: сессия ``appA`` вытеснялась, хотя ею пользовался активный
  пользователь (``appA-evicted``).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.services.rpa.desktop_session_pool import (
    DesktopRPASessionPool,
    PoolCapacityError,
)

pytestmark = pytest.mark.unit


def _pool(*, max_sessions: int = 2) -> DesktopRPASessionPool:
    """Пул с заданным лимитом сессий."""
    return DesktopRPASessionPool(
        base_url="http://rpa-test:8080",
        timeout=1.0,
        ttl_seconds=60.0,
        max_sessions=max_sessions,
    )


def _client() -> MagicMock:
    """Мок httpx-клиента с корректным async-интерфейсом."""
    client = MagicMock()
    client.aclose = AsyncMock(return_value=None)
    client.get = AsyncMock()
    client.post = AsyncMock()
    return client


def _patch_make() -> Any:
    """Подмена ``make_http_client`` — каждый вызов даёт новый мок-клиент."""
    return patch(
        "src.backend.services.rpa.desktop_session_pool.make_http_client",
        side_effect=lambda **kwargs: _client(),
    )


@pytest.mark.asyncio
async def test_max_sessions_is_enforced() -> None:
    """Пул не превышает ``max_sessions`` (регрессия: total=3 при max=2)."""
    pool = _pool(max_sessions=2)
    with _patch_make():
        async with pool.acquire("appA"):
            pass
        async with pool.acquire("appB"):
            pass
        async with pool.acquire("appC"):
            pass

    stats = await pool.stats()
    assert stats.total <= 2


@pytest.mark.asyncio
async def test_eviction_does_not_close_active_session() -> None:
    """Активная сессия не вытесняется (регрессия: ``appA-evicted``)."""
    pool = _pool(max_sessions=1)
    with _patch_make():
        async with pool.acquire("appA"):
            # Лимит исчерпан, а единственная сессия активна → вытеснять
            # нечего: новая не создаётся, активная не закрывается.
            with pytest.raises(PoolCapacityError):
                async with pool.acquire("appB"):
                    pass
            stats = await pool.stats()
            assert "appA" in stats.by_app
            assert stats.by_app["appA"]["in_use"] is True
            assert stats.by_app["appA"]["active_users"] == 1


@pytest.mark.asyncio
async def test_idle_session_is_evicted_first() -> None:
    """При достижении лимита вытесняется самая старая idle-сессия."""
    pool = _pool(max_sessions=2)
    with _patch_make():
        async with pool.acquire("appA"):
            pass
        async with pool.acquire("appB"):
            pass
        async with pool.acquire("appC"):
            pass

    stats = await pool.stats()
    assert "appC" in stats.by_app
    assert "appA" not in stats.by_app


@pytest.mark.asyncio
async def test_active_users_counter_tracks_concurrent_users() -> None:
    """Счётчик активных пользователей растёт при параллельном acquire."""
    pool = _pool(max_sessions=4)
    with _patch_make():
        async with pool.acquire("appA"):
            stats = await pool.stats()
            assert stats.by_app["appA"]["active_users"] == 1
        stats = await pool.stats()
        assert stats.by_app["appA"]["active_users"] == 0


@pytest.mark.asyncio
async def test_capacity_error_message_mentions_limit() -> None:
    """Ошибка исчерпания пула понятна (имя лимита и цель)."""
    pool = _pool(max_sessions=1)
    with _patch_make():
        async with pool.acquire("appA"):
            with pytest.raises(PoolCapacityError) as exc_info:
                async with pool.acquire("appB"):
                    pass
    assert "max_sessions=1" in str(exc_info.value)
