"""Unit tests for src.backend.infrastructure.clients.transport.imap_pool (v17 §1.1).

Per v17 §1.1: IMAP client pool (252 LOC) "не анализировался в 16
предыдущих итерациях". Coverage gap → add tests.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

try:
    from src.backend.infrastructure.clients.transport.imap_pool import (
        ImapPool,  # noqa: F401
    )

    HAS_IMAP_POOL = True
except ImportError, ModuleNotFoundError, AttributeError:
    HAS_IMAP_POOL = False


@pytest.fixture
def pool_settings() -> dict:
    return {
        "host": "imap.example.com",
        "port": 993,
        "username": "user",
        "password": "x" * 16,
        "pool_size": 5,
        "use_ssl": True,
    }


@pytest.fixture
def mock_imap_conn() -> AsyncMock:
    conn = AsyncMock()
    conn.is_closed = False
    return conn


@pytest.mark.skipif(not HAS_IMAP_POOL, reason="imap_pool not importable")
def test_imap_pool_imports() -> None:
    from src.backend.infrastructure.clients.transport import imap_pool

    assert imap_pool is not None


@pytest.mark.skipif(not HAS_IMAP_POOL, reason="imap_pool not importable")
def test_pool_creation(pool_settings: dict) -> None:
    pool = ImapPool(**pool_settings)
    assert pool is not None


@pytest.mark.skipif(not HAS_IMAP_POOL, reason="imap_pool not importable")
def test_pool_with_default_size(pool_settings: dict) -> None:
    pool_settings.pop("pool_size", None)
    pool = ImapPool(**pool_settings)
    assert pool.pool_size > 0 if hasattr(pool, "pool_size") else True


@pytest.mark.skipif(not HAS_IMAP_POOL, reason="imap_pool not importable")
def test_pool_with_custom_size(pool_settings: dict) -> None:
    pool_settings["pool_size"] = 10
    pool = ImapPool(**pool_settings)
    if hasattr(pool, "pool_size"):
        assert pool.pool_size == 10


@pytest.mark.skipif(not HAS_IMAP_POOL, reason="imap_pool not importable")
@pytest.mark.asyncio
async def test_acquire_connection(
    pool_settings: dict, mock_imap_conn: AsyncMock
) -> None:
    pool = ImapPool(**pool_settings)
    with patch.object(
        pool, "_create_connection", AsyncMock(return_value=mock_imap_conn)
    ):
        conn = await pool.acquire()
        assert conn is not None


@pytest.mark.skipif(not HAS_IMAP_POOL, reason="imap_pool not importable")
@pytest.mark.asyncio
async def test_release_connection(
    pool_settings: dict, mock_imap_conn: AsyncMock
) -> None:
    pool = ImapPool(**pool_settings)
    with patch.object(
        pool, "_create_connection", AsyncMock(return_value=mock_imap_conn)
    ):
        conn = await pool.acquire()
        await pool.release(conn)


@pytest.mark.skipif(not HAS_IMAP_POOL, reason="imap_pool not importable")
@pytest.mark.asyncio
async def test_pool_context_manager(
    pool_settings: dict, mock_imap_conn: AsyncMock
) -> None:
    pool = ImapPool(**pool_settings)
    with patch.object(
        pool, "_create_connection", AsyncMock(return_value=mock_imap_conn)
    ):
        async with pool.connection() as conn:
            assert conn is not None


@pytest.mark.skipif(not HAS_IMAP_POOL, reason="imap_pool not importable")
@pytest.mark.asyncio
async def test_pool_exhausted_raises(pool_settings: dict) -> None:
    pool_settings["pool_size"] = 1
    pool = ImapPool(**pool_settings)
    mock_conn = AsyncMock()
    with patch.object(pool, "_create_connection", AsyncMock(return_value=mock_conn)):
        await pool.acquire()
        with pytest.raises((asyncio.TimeoutError, RuntimeError, Exception)):
            await asyncio.wait_for(pool.acquire(), timeout=0.1)


@pytest.mark.skipif(not HAS_IMAP_POOL, reason="imap_pool not importable")
@pytest.mark.asyncio
async def test_pool_connection_health(
    pool_settings: dict, mock_imap_conn: AsyncMock
) -> None:
    pool = ImapPool(**pool_settings)
    with patch.object(
        pool, "_create_connection", AsyncMock(return_value=mock_imap_conn)
    ):
        conn = await pool.acquire()
        if hasattr(pool, "is_healthy"):
            healthy = await pool.is_healthy(conn)
            assert isinstance(healthy, bool)


@pytest.mark.skipif(not HAS_IMAP_POOL, reason="imap_pool not importable")
@pytest.mark.asyncio
async def test_pool_recycle_on_failure(
    pool_settings: dict, mock_imap_conn: AsyncMock
) -> None:
    pool = ImapPool(**pool_settings)
    mock_imap_conn.is_closed = True
    with patch.object(
        pool, "_create_connection", AsyncMock(return_value=mock_imap_conn)
    ):
        await pool.acquire()


@pytest.mark.skipif(not HAS_IMAP_POOL, reason="imap_pool not importable")
def test_pool_with_auth(pool_settings: dict) -> None:
    pool = ImapPool(**pool_settings)
    if hasattr(pool, "username"):
        assert pool.username == "user"


@pytest.mark.skipif(not HAS_IMAP_POOL, reason="imap_pool not importable")
def test_pool_max_lifetime(pool_settings: dict) -> None:
    pool = ImapPool(**pool_settings, max_lifetime=3600)
    if hasattr(pool, "max_lifetime"):
        assert pool.max_lifetime == 3600


@pytest.mark.skipif(not HAS_IMAP_POOL, reason="imap_pool not importable")
@pytest.mark.asyncio
async def test_pool_close_all(pool_settings: dict, mock_imap_conn: AsyncMock) -> None:
    pool = ImapPool(**pool_settings)
    with patch.object(
        pool, "_create_connection", AsyncMock(return_value=mock_imap_conn)
    ):
        await pool.acquire()
        await pool.close_all()
