"""Tests for transport health facade (Milestone 1)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from src.backend.infrastructure.clients.transport.health import (
    _TRACKED_CONNECTORS,
    HEALTH_CHECK_TIMEOUT,
    check_all_transport,
    get_transport_health,
)


class TestGetTransportHealth:
    async def test_unknown_connector_returns_false(self) -> None:
        """Unknown name → False (не raises)."""
        result = await get_transport_health("nonexistent_xyz")
        assert result is False

    async def test_known_connector_returns_true_when_module_has_client(self) -> None:
        """Mock module with Client attr → True."""
        with patch(
            "importlib.import_module",
            return_value=type("M", (), {"Client": object}),
        ):
            result = await get_transport_health("http")
        assert result is True

    async def test_async_is_healthy_true(self) -> None:
        """Async is_healthy() returning True propagates."""
        mock_module = type(
            "M",
            (),
            {"is_healthy": AsyncMock(return_value=True)},
        )
        with patch("importlib.import_module", return_value=mock_module):
            result = await get_transport_health("smtp")
        assert result is True

    async def test_async_is_healthy_false(self) -> None:
        """Async is_healthy() returning False propagates."""
        mock_module = type(
            "M",
            (),
            {"is_healthy": AsyncMock(return_value=False)},
        )
        with patch("importlib.import_module", return_value=mock_module):
            result = await get_transport_health("smtp")
        assert result is False

    async def test_timeout_returns_false(self) -> None:
        """Slow is_healthy → TimeoutError → False."""
        import asyncio

        async def slow_check() -> bool:
            await asyncio.sleep(10)
            return True

        mock_module = type("M", (), {"is_healthy": slow_check})
        with patch("importlib.import_module", return_value=mock_module):
            result = await get_transport_health("smtp", timeout=0.05)
        assert result is False

    async def test_import_error_returns_false(self) -> None:
        """ImportError → False (не crashes)."""
        with patch(
            "importlib.import_module",
            side_effect=ImportError("not installed"),
        ):
            result = await get_transport_health("smtp")
        assert result is False


class TestCheckAllTransport:
    async def test_returns_all_tracked(self) -> None:
        """Возвращает все connectors из _TRACKED_CONNECTORS."""
        with patch(
            "src.backend.infrastructure.clients.transport.health.get_transport_health",
            new=AsyncMock(return_value=True),
        ):
            report = await check_all_transport()
        assert set(report.keys()) == set(_TRACKED_CONNECTORS)
        assert all(report.values())

    async def test_partial_health(self) -> None:
        """Часть connectors healthy, часть нет."""
        async def mixed(name: str, *, timeout: float = 2.0) -> bool:
            return name in {"http", "smtp"}

        with patch(
            "src.backend.infrastructure.clients.transport.health.get_transport_health",
            side_effect=mixed,
        ):
            report = await check_all_transport()
        assert report["http"] is True
        assert report["smtp"] is True
        assert report["sftp"] is False

    async def test_sequential_mode(self) -> None:
        """concurrent=False работает так же."""
        with patch(
            "src.backend.infrastructure.clients.transport.health.get_transport_health",
            new=AsyncMock(return_value=True),
        ):
            report = await check_all_transport(concurrent=False)
        assert len(report) == len(_TRACKED_CONNECTORS)


class TestHealthCheckConstants:
    def test_default_timeout_is_2_seconds(self) -> None:
        """Sensible default для health probes."""
        assert HEALTH_CHECK_TIMEOUT == 2.0

    def test_tracked_connectors_include_essentials(self) -> None:
        """Критичные transport-клиенты покрыты."""
        assert "http" in _TRACKED_CONNECTORS
        assert "smtp" in _TRACKED_CONNECTORS
        assert "sftp" in _TRACKED_CONNECTORS
