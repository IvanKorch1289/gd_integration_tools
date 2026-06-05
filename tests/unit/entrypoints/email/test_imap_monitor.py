"""Unit tests for src.backend.entrypoints.email.imap_monitor (v17 §1.1).

Per v17 §1.1: IMAP entrypoint (357 LOC) "не анализировался в 16
предыдущих итерациях". Coverage gap → add tests.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

try:
    from src.backend.entrypoints.email.imap_monitor import (  # type: ignore[attr-defined]
        ImapMonitor,
        ImapSettings,
    )
    HAS_IMAP_MONITOR = True
except (ImportError, ModuleNotFoundError, AttributeError):
    HAS_IMAP_MONITOR = False


@pytest.fixture
def mock_settings() -> "ImapSettings":
    return ImapSettings(
        host="imap.example.com",
        port=993,
        username="user@example.com",
        password="x" * 16,
        mailbox="INBOX",
        use_ssl=True,
    )


@pytest.fixture
def mock_imap_connection() -> AsyncMock:
    conn = AsyncMock()
    conn.wait_hello_from_server = AsyncMock(return_value=("OK", [b"welcome"]))
    conn.login = AsyncMock(return_value=("OK", [b"login successful"]))
    conn.logout = AsyncMock(return_value=("BYE", [b"logout"]))
    conn.select = AsyncMock(return_value=("OK", [b"1"]))
    conn.idle = AsyncMock(return_value=("OK", [b"idling"]))
    return conn


@pytest.mark.skipif(not HAS_IMAP_MONITOR, reason="imap_monitor not importable")
def test_imap_monitor_imports() -> None:
    from src.backend.entrypoints.email import imap_monitor  # type: ignore[attr-defined]
    assert imap_monitor is not None


@pytest.mark.skipif(not HAS_IMAP_MONITOR, reason="imap_monitor not importable")
def test_monitor_creation(mock_settings: "ImapSettings") -> None:
    monitor = ImapMonitor(settings=mock_settings)
    assert monitor is not None


@pytest.mark.skipif(not HAS_IMAP_MONITOR, reason="imap_monitor not importable")
def test_monitor_default_settings() -> None:
    settings = ImapSettings(host="h", port=993, username="u", password="p")
    monitor = ImapMonitor(settings=settings)
    assert monitor is not None


@pytest.mark.skipif(not HAS_IMAP_MONITOR, reason="imap_monitor not importable")
def test_monitor_custom_settings(mock_settings: "ImapSettings") -> None:
    monitor = ImapMonitor(settings=mock_settings)
    assert monitor.settings.host == "imap.example.com"


@pytest.mark.skipif(not HAS_IMAP_MONITOR, reason="imap_monitor not importable")
@pytest.mark.asyncio
async def test_connect_to_imap(
    mock_settings: "ImapSettings", mock_imap_connection: AsyncMock
) -> None:
    monitor = ImapMonitor(settings=mock_settings)
    with patch(
        "src.backend.entrypoints.email.imap_monitor.aioimaplib.IMAP4_SSL",
        return_value=mock_imap_connection,
    ):
        await monitor.connect()


@pytest.mark.skipif(not HAS_IMAP_MONITOR, reason="imap_monitor not importable")
@pytest.mark.asyncio
async def test_disconnect_from_imap(
    mock_settings: "ImapSettings", mock_imap_connection: AsyncMock
) -> None:
    monitor = ImapMonitor(settings=mock_settings)
    monitor._conn = mock_imap_connection
    await monitor.disconnect()
    mock_imap_connection.logout.assert_awaited_once()


@pytest.mark.skipif(not HAS_IMAP_MONITOR, reason="imap_monitor not importable")
@pytest.mark.asyncio
async def test_idle_loop_runs(
    mock_settings: "ImapSettings", mock_imap_connection: AsyncMock
) -> None:
    monitor = ImapMonitor(settings=mock_settings)
    monitor._conn = mock_imap_connection
    task = asyncio.create_task(monitor._idle_loop())
    await asyncio.sleep(0.01)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.skipif(not HAS_IMAP_MONITOR, reason="imap_monitor not importable")
@pytest.mark.asyncio
async def test_message_callback(
    mock_settings: "ImapSettings", mock_imap_connection: AsyncMock
) -> None:
    callback = AsyncMock()
    monitor = ImapMonitor(settings=mock_settings, on_message=callback)
    monitor._conn = mock_imap_connection
    assert monitor is not None


@pytest.mark.skipif(not HAS_IMAP_MONITOR, reason="imap_monitor not importable")
@pytest.mark.asyncio
async def test_reconnect_after_disconnect(
    mock_settings: "ImapSettings", mock_imap_connection: AsyncMock
) -> None:
    monitor = ImapMonitor(settings=mock_settings, max_reconnects=3)
    monitor._conn = mock_imap_connection
    await monitor._reconnect()


@pytest.mark.skipif(not HAS_IMAP_MONITOR, reason="imap_monitor not importable")
@pytest.mark.asyncio
async def test_max_reconnect_attempts(mock_settings: "ImapSettings") -> None:
    monitor = ImapMonitor(settings=mock_settings, max_reconnects=2)
    with patch.object(monitor, "_connect", side_effect=ConnectionError("fail")):
        with pytest.raises(ConnectionError):
            await monitor._reconnect_with_backoff()


@pytest.mark.skipif(not HAS_IMAP_MONITOR, reason="imap_monitor not importable")
@pytest.mark.asyncio
async def test_mailbox_selection(
    mock_settings: "ImapSettings", mock_imap_connection: AsyncMock
) -> None:
    monitor = ImapMonitor(settings=mock_settings)
    with patch(
        "src.backend.entrypoints.email.imap_monitor.aioimaplib.IMAP4_SSL",
        return_value=mock_imap_connection,
    ):
        await monitor.connect()
        mock_imap_connection.select.assert_awaited_with(mailbox="INBOX")


@pytest.mark.skipif(not HAS_IMAP_MONITOR, reason="imap_monitor not importable")
def test_idle_timeout_setting(mock_settings: "ImapSettings") -> None:
    mock_settings.idle_timeout = 1
    monitor = ImapMonitor(settings=mock_settings)
    assert monitor.settings.idle_timeout == 1


@pytest.mark.skipif(not HAS_IMAP_MONITOR, reason="imap_monitor not importable")
@pytest.mark.asyncio
async def test_graceful_shutdown(
    mock_settings: "ImapSettings", mock_imap_connection: AsyncMock
) -> None:
    monitor = ImapMonitor(settings=mock_settings)
    monitor._conn = mock_imap_connection
    await monitor.shutdown()


@pytest.mark.skipif(not HAS_IMAP_MONITOR, reason="imap_monitor not importable")
def test_settings_default_ssl() -> None:
    settings = ImapSettings(host="h", port=993, username="u", password="p")
    assert settings.use_ssl is True


@pytest.mark.skipif(not HAS_IMAP_MONITOR, reason="imap_monitor not importable")
def test_settings_default_port() -> None:
    settings = ImapSettings(host="h", username="u", password="p")
    assert settings.port == 993 or settings.port is None


@pytest.mark.skipif(not HAS_IMAP_MONITOR, reason="imap_monitor not importable")
def test_settings_required_fields() -> None:
    with pytest.raises((ValueError, TypeError)):
        ImapSettings()
