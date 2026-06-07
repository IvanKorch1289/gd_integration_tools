# ruff: noqa: S101
"""Unit tests for AdminService (services/core/admin.py)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from src.backend.services.core.admin import AdminService, get_admin_service


@pytest.fixture(autouse=True)
def _reset_singleton() -> Any:
    import src.backend.services.core.admin as _mod

    _mod._instance = None
    yield
    _mod._instance = None


@pytest.fixture()
def service() -> AdminService:
    return AdminService()


# ── config ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_config_returns_settings_dump(service: AdminService) -> None:
    with patch("src.backend.services.core.admin.settings") as mock_settings:
        mock_settings.model_dump.return_value = {"env": "test"}
        result = await service.get_config()
        assert result == {"env": "test"}


# ── toggle route ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_toggle_route_enables(service: AdminService) -> None:
    request = MagicMock()
    request.app.routes = [MagicMock(path="/api/v1/test")]
    with patch("src.backend.core.state.runtime.blocked_routes", set()) as br:
        result = await service.toggle_route(request, "/api/v1/test", enable=True)
        assert result == {"status": "success"}
        assert "/api/v1/test" not in br


@pytest.mark.asyncio
async def test_toggle_route_disables(service: AdminService) -> None:
    request = MagicMock()
    request.app.routes = [MagicMock(path="/api/v1/test")]
    with patch("src.backend.core.state.runtime.blocked_routes", set()) as br:
        result = await service.toggle_route(request, "/api/v1/test", enable=False)
        assert result == {"status": "success"}
        assert "/api/v1/test" in br


@pytest.mark.asyncio
async def test_toggle_route_raises_404_when_missing(service: AdminService) -> None:
    request = MagicMock()
    request.app.routes = []
    with pytest.raises(HTTPException) as exc_info:
        await service.toggle_route(request, "/missing", enable=True)
    assert exc_info.value.status_code == 404


# ── cache ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_cache_keys(service: AdminService) -> None:
    with patch(
        "src.backend.services.core.admin.get_admin_cache_storage_provider"
    ) as mock_provider:
        mock_provider.return_value.list_cache_keys = AsyncMock(return_value=["k1"])
        result = await service.list_cache_keys(pattern="*")
        assert result == ["k1"]


@pytest.mark.asyncio
async def test_get_cache_value(service: AdminService) -> None:
    with patch(
        "src.backend.services.core.admin.get_admin_cache_storage_provider"
    ) as mock_provider:
        mock_provider.return_value.get_cache_value = AsyncMock(return_value="v1")
        result = await service.get_cache_value("key")
        assert result == "v1"


@pytest.mark.asyncio
async def test_invalidate_cache(service: AdminService) -> None:
    with patch(
        "src.backend.services.core.admin.get_admin_cache_storage_provider"
    ) as mock_provider:
        mock_provider.return_value.invalidate_cache = AsyncMock(return_value=5)
        result = await service.invalidate_cache()
        assert result == 5


@pytest.mark.asyncio
async def test_invalidate_cache_by_pattern(service: AdminService) -> None:
    with patch(
        "src.backend.core.di.providers.get_cache_invalidator_provider"
    ) as mock_provider:
        mock_provider.return_value.invalidate_pattern = AsyncMock(return_value=3)
        result = await service.invalidate_cache_by_pattern("entity:*")
        assert result == {"pattern": "entity:*", "removed": 3}


@pytest.mark.asyncio
async def test_invalidate_cache_by_tag(service: AdminService) -> None:
    with patch(
        "src.backend.core.di.providers.get_cache_invalidator_provider"
    ) as mock_provider:
        mock_provider.return_value.invalidate_tags = AsyncMock(return_value=2)
        result = await service.invalidate_cache_by_tag(["tag:a", "tag:b"])
        assert result == {"tags": ["tag:a", "tag:b"], "removed": 2}


@pytest.mark.asyncio
async def test_invalidate_table(service: AdminService) -> None:
    with patch(
        "src.backend.core.di.providers.get_cache_invalidator_provider"
    ) as mock_provider:
        mock_provider.return_value.invalidate_tags = AsyncMock(return_value=4)
        result = await service.invalidate_table("orders")
        assert result == {"table": "orders", "tag": "table:orders", "removed": 4}


# ── introspection ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_services(service: AdminService) -> None:
    with patch("src.backend.services.core.admin._list_services", return_value=["svc"]):
        result = await service.list_services()
        assert result == {"services": ["svc"]}


@pytest.mark.asyncio
async def test_list_actions(service: AdminService) -> None:
    mock_registry = MagicMock()
    mock_registry.list_actions.return_value = ["a1", "a2"]
    with patch(
        "src.backend.services.core.admin.action_handler_registry", mock_registry
    ):
        result = await service.list_actions()
        assert result == {"actions": ["a1", "a2"]}


@pytest.mark.asyncio
async def test_list_routes(service: AdminService) -> None:
    mock_registry = MagicMock()
    mock_registry.list_routes.return_value = ["r1"]
    mock_registry.list_enabled_routes.return_value = ["r1"]
    mock_registry.get_route_feature_flags.return_value = {}
    with patch("src.backend.services.core.admin.route_registry", mock_registry):
        result = await service.list_routes()
        assert result["total"] == 1
        assert result["routes"][0]["route_id"] == "r1"


@pytest.mark.asyncio
async def test_list_feature_flags(service: AdminService) -> None:
    mock_registry = MagicMock()
    mock_registry.get_route_feature_flags.return_value = {"r1": "flag_a"}
    with patch("src.backend.services.core.admin.route_registry", mock_registry):
        with patch(
            "src.backend.services.core.admin.disabled_feature_flags", {"flag_b"}
        ):
            result = await service.list_feature_flags()
            assert len(result["flags"]) == 1
            assert result["flags"][0]["name"] == "flag_a"
            assert result["flags"][0]["enabled"] is True


@pytest.mark.asyncio
async def test_toggle_feature_flag(service: AdminService) -> None:
    mock_registry = MagicMock()
    mock_registry.get_route_feature_flags.return_value = {"r1": "flag_a"}
    with patch("src.backend.services.core.admin.route_registry", mock_registry):
        result = await service.toggle_feature_flag("flag_a", enable=False)
        assert result["flag"] == "flag_a"
        assert result["enabled"] is False
        mock_registry.toggle_feature_flag.assert_called_once_with(
            "flag_a", enable=False
        )


@pytest.mark.asyncio
async def test_system_info(service: AdminService) -> None:
    mock_route = MagicMock()
    mock_route.list_routes.return_value = ["r1"]
    mock_route.list_enabled_routes.return_value = ["r1"]
    mock_route.list_disabled_routes.return_value = []
    mock_action = MagicMock()
    mock_action.list_actions.return_value = ["a1"]
    with patch("src.backend.services.core.admin.route_registry", mock_route):
        with patch(
            "src.backend.services.core.admin.action_handler_registry", mock_action
        ):
            with patch(
                "src.backend.services.core.admin.disabled_feature_flags", {"f1"}
            ):
                with patch(
                    "src.backend.services.core.admin._list_services",
                    return_value=["svc"],
                ):
                    result = await service.system_info()
                    assert result["routes_total"] == 1
                    assert result["routes_enabled"] == 1
                    assert result["routes_disabled"] == 0
                    assert result["feature_flags_disabled"] == ["f1"]


# ── slo report ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_slo_report(service: AdminService) -> None:
    with patch(
        "src.backend.services.core.admin.get_slo_tracker_provider"
    ) as mock_provider:
        mock_provider.return_value.get_report.return_value = {"p99": 50}
        result = await service.slo_report()
        assert result == {"p99": 50}


# ── singleton ───────────────────────────────────────────────────


def test_get_admin_service_singleton() -> None:
    s1 = get_admin_service()
    s2 = get_admin_service()
    assert s1 is s2
