# ruff: noqa: S101
"""Unit tests for SystemService (services/core/system.py)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.services.core.system import SystemService, get_system_service


@pytest.fixture(autouse=True)
def _reset_singleton() -> Any:
    import src.backend.services.core.system as _mod

    _mod._instance = None
    yield
    _mod._instance = None


@pytest.fixture()
def service() -> SystemService:
    return SystemService()


@pytest.fixture()
def mock_admin() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def mock_tech() -> AsyncMock:
    return AsyncMock()


# ── health ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_uses_aggregator_when_available(service: SystemService) -> None:
    with patch(
        "src.backend.services.core.system.get_health_aggregator_provider"
    ) as mock_provider:
        aggregator = AsyncMock()
        aggregator.check_all.return_value = {"ok": True}
        mock_provider.return_value = aggregator
        result = await service.health()
        assert result == {"ok": True}
        aggregator.check_all.assert_awaited_once()


@pytest.mark.asyncio
async def test_health_falls_back_to_tech_on_import_error(
    service: SystemService, mock_tech: AsyncMock
) -> None:
    with patch(
        "src.backend.services.core.system.get_health_aggregator_provider",
        side_effect=ImportError,
    ):
        with patch(
            "src.backend.services.core.system.get_tech_service", return_value=mock_tech
        ):
            mock_tech.check_all_services.return_value = {"fallback": True}
            result = await service.health()
            assert result == {"fallback": True}


@pytest.mark.asyncio
async def test_component_health_delegates_to_aggregator(service: SystemService) -> None:
    with patch(
        "src.backend.services.core.system.get_health_aggregator_provider"
    ) as mock_provider:
        aggregator = AsyncMock()
        aggregator.check_single.return_value = {"db": True}
        mock_provider.return_value = aggregator
        result = await service.component_health("db")
        assert result == {"db": True}
        aggregator.check_single.assert_awaited_once_with("db")


# ── config / feature flags ──────────────────────────────────────

@pytest.mark.asyncio
async def test_get_config_delegates_to_admin(
    service: SystemService, mock_admin: AsyncMock
) -> None:
    with patch(
        "src.backend.services.core.system.get_admin_service", return_value=mock_admin
    ):
        mock_admin.get_config.return_value = {"env": "test"}
        result = await service.get_config()
        assert result == {"env": "test"}


@pytest.mark.asyncio
async def test_list_feature_flags_delegates_to_admin(
    service: SystemService, mock_admin: AsyncMock
) -> None:
    with patch(
        "src.backend.services.core.system.get_admin_service", return_value=mock_admin
    ):
        mock_admin.list_feature_flags.return_value = {"flags": []}
        result = await service.list_feature_flags()
        assert result == {"flags": []}


@pytest.mark.asyncio
async def test_toggle_feature_flag_delegates_to_admin(
    service: SystemService, mock_admin: AsyncMock
) -> None:
    with patch(
        "src.backend.services.core.system.get_admin_service", return_value=mock_admin
    ):
        mock_admin.toggle_feature_flag.return_value = {"flag": "x", "enabled": True}
        result = await service.toggle_feature_flag("x", True)
        assert result["enabled"] is True
        mock_admin.toggle_feature_flag.assert_awaited_once_with(flag="x", enabled=True)


# ── introspection ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_services_delegates_to_admin(
    service: SystemService, mock_admin: AsyncMock
) -> None:
    with patch(
        "src.backend.services.core.system.get_admin_service", return_value=mock_admin
    ):
        mock_admin.list_services.return_value = [{"name": "svc"}]
        result = await service.list_services()
        assert result == [{"name": "svc"}]


@pytest.mark.asyncio
async def test_list_actions_delegates_to_admin(
    service: SystemService, mock_admin: AsyncMock
) -> None:
    with patch(
        "src.backend.services.core.system.get_admin_service", return_value=mock_admin
    ):
        mock_admin.list_actions.return_value = ["a1", "a2"]
        result = await service.list_actions()
        assert result == ["a1", "a2"]


@pytest.mark.asyncio
async def test_list_routes_delegates_to_admin(
    service: SystemService, mock_admin: AsyncMock
) -> None:
    with patch(
        "src.backend.services.core.system.get_admin_service", return_value=mock_admin
    ):
        mock_admin.list_routes.return_value = [{"id": "r1"}]
        result = await service.list_routes()
        assert result == [{"id": "r1"}]


# ── cache management ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_cache_keys_delegates_to_admin(
    service: SystemService, mock_admin: AsyncMock
) -> None:
    with patch(
        "src.backend.services.core.system.get_admin_service", return_value=mock_admin
    ):
        mock_admin.list_cache_keys.return_value = ["k1", "k2"]
        result = await service.list_cache_keys(pattern="test:*")
        assert result == ["k1", "k2"]
        mock_admin.list_cache_keys.assert_awaited_once_with(pattern="test:*")


@pytest.mark.asyncio
async def test_invalidate_cache_delegates_to_admin(
    service: SystemService, mock_admin: AsyncMock
) -> None:
    with patch(
        "src.backend.services.core.system.get_admin_service", return_value=mock_admin
    ):
        mock_admin.invalidate_cache_by_pattern.return_value = {"removed": 5}
        result = await service.invalidate_cache(pattern="test:*")
        assert result == {"removed": 5}


# ── slo report ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_slo_report_uses_tracker(service: SystemService) -> None:
    with patch(
        "src.backend.services.core.system.get_slo_tracker_provider"
    ) as mock_provider:
        tracker = MagicMock()
        tracker.get_report.return_value = {"p99": 100}
        mock_provider.return_value = tracker
        result = await service.slo_report()
        assert result == {"p99": 100}


@pytest.mark.asyncio
async def test_slo_report_returns_empty_on_import_error(service: SystemService) -> None:
    with patch(
        "src.backend.services.core.system.get_slo_tracker_provider",
        side_effect=ImportError,
    ):
        result = await service.slo_report()
        assert result == {}


# ── notifications ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_email_delegates_to_tech(
    service: SystemService, mock_tech: AsyncMock
) -> None:
    with patch(
        "src.backend.services.core.system.get_tech_service", return_value=mock_tech
    ):
        mock_tech.send_email.return_value = {"sent": True}
        result = await service.send_email(to="a@b.com", subject="hi")
        assert result == {"sent": True}
        mock_tech.send_email.assert_awaited_once_with(to="a@b.com", subject="hi")


# ── lazy properties ─────────────────────────────────────────────

def test_tech_property_lazy_loads() -> None:
    svc = SystemService()
    assert svc._tech is None
    with patch(
        "src.backend.services.core.system.get_tech_service"
    ) as mock_get_tech:
        mock_tech = MagicMock()
        mock_get_tech.return_value = mock_tech
        t = svc.tech
        assert t is mock_tech
        assert svc._tech is mock_tech
        mock_get_tech.assert_called_once()


def test_admin_property_lazy_loads() -> None:
    svc = SystemService()
    assert svc._admin is None
    with patch(
        "src.backend.services.core.system.get_admin_service"
    ) as mock_get_admin:
        mock_admin = MagicMock()
        mock_get_admin.return_value = mock_admin
        a = svc.admin
        assert a is mock_admin
        assert svc._admin is mock_admin
        mock_get_admin.assert_called_once()


# ── singleton ───────────────────────────────────────────────────

def test_get_system_service_singleton() -> None:
    s1 = get_system_service()
    s2 = get_system_service()
    assert s1 is s2
