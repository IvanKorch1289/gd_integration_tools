"""Unit tests for health endpoints."""

# ruff: noqa: S101

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request

from src.backend.entrypoints.api.v1.endpoints import health as health_mod


class TestLivenessProbe:
    @pytest.mark.asyncio
    async def test_returns_alive(self) -> None:
        resp = await health_mod.liveness_probe()
        assert resp.status_code == 200
        assert resp.body is not None
        body = resp.body.decode()
        assert "alive" in body


class TestReadinessProbe:
    @pytest.mark.asyncio
    async def test_initializing(self) -> None:
        request = MagicMock(spec=Request)
        request.app.state.infrastructure_ready = False
        resp = await health_mod.readiness_probe(request)
        assert resp.status_code == 503
        assert b"initializing" in resp.body

    @pytest.mark.asyncio
    async def test_ready(self) -> None:
        request = MagicMock(spec=Request)
        request.app.state.infrastructure_ready = True
        with patch(
            "src.backend.core.di.providers.get_resilience_coordinator_provider"
        ) as mock_get:
            coord = MagicMock()
            coord.status.return_value = {}
            mock_get.return_value = coord
            resp = await health_mod.readiness_probe(request)
        assert resp.status_code == 200
        assert b"ready" in resp.body

    @pytest.mark.asyncio
    async def test_degraded(self) -> None:
        request = MagicMock(spec=Request)
        request.app.state.infrastructure_ready = True
        with patch(
            "src.backend.core.di.providers.get_resilience_coordinator_provider"
        ) as mock_get:
            comp = MagicMock()
            comp.degradation = "degraded"
            coord = MagicMock()
            coord.status.return_value = {"db": comp}
            mock_get.return_value = coord
            resp = await health_mod.readiness_probe(request)
        assert resp.status_code == 200
        assert b"degraded" in resp.body

    @pytest.mark.asyncio
    async def test_not_ready(self) -> None:
        request = MagicMock(spec=Request)
        request.app.state.infrastructure_ready = True
        with patch(
            "src.backend.core.di.providers.get_resilience_coordinator_provider"
        ) as mock_get:
            comp = MagicMock()
            comp.degradation = "down"
            coord = MagicMock()
            coord.status.return_value = {"db": comp}
            mock_get.return_value = coord
            resp = await health_mod.readiness_probe(request)
        assert resp.status_code == 503
        assert b"not_ready" in resp.body

    @pytest.mark.asyncio
    async def test_health_check_failed(self) -> None:
        request = MagicMock(spec=Request)
        request.app.state.infrastructure_ready = True
        with patch(
            "src.backend.core.di.providers.get_resilience_coordinator_provider"
        ) as mock_get:
            mock_get.side_effect = RuntimeError("fail")
            resp = await health_mod.readiness_probe(request)
        assert resp.status_code == 503
        assert b"health_check_failed" in resp.body


class TestStartupProbe:
    @pytest.mark.asyncio
    async def test_starting(self) -> None:
        request = MagicMock(spec=Request)
        request.app.state.infrastructure_ready = False
        resp = await health_mod.startup_probe(request)
        assert resp.status_code == 503
        assert b"starting" in resp.body

    @pytest.mark.asyncio
    async def test_started(self) -> None:
        request = MagicMock(spec=Request)
        request.app.state.infrastructure_ready = True
        with (
            patch(
                "src.backend.dsl.commands.registry.action_handler_registry"
            ) as mock_actions,
            patch("src.backend.dsl.commands.registry.route_registry") as mock_routes,
        ):
            mock_actions.list_actions.return_value = ["a", "b"]
            mock_routes.list_routes.return_value = ["r1"]
            resp = await health_mod.startup_probe(request)
        assert resp.status_code == 200
        assert b"started" in resp.body


class TestComponentsHealth:
    @pytest.mark.asyncio
    async def test_invalid_mode(self) -> None:
        resp = await health_mod.components_health(mode="invalid")
        assert resp.status_code == 400
        assert b"invalid mode" in resp.body

    @pytest.mark.asyncio
    async def test_fast_mode(self) -> None:
        with patch(
            "src.backend.core.di.providers.get_health_aggregator_provider"
        ) as mock_get:
            agg = AsyncMock()
            agg.check_all.return_value = {"status": "ok", "components": {}}
            mock_get.return_value = agg
            resp = await health_mod.components_health(mode="fast")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_deep_mode(self) -> None:
        with (
            patch(
                "src.backend.core.di.providers.get_health_aggregator_provider"
            ) as mock_get,
            patch(
                "src.backend.core.di.providers.get_resilience_components_report_provider"
            ) as mock_res,
        ):
            agg = AsyncMock()
            agg.check_all.return_value = {"status": "ok", "components": {}}
            mock_get.return_value = agg
            mock_res.return_value = lambda: {"chains": []}
            resp = await health_mod.components_health(mode="deep")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_down_status(self) -> None:
        with patch(
            "src.backend.core.di.providers.get_health_aggregator_provider"
        ) as mock_get:
            agg = AsyncMock()
            agg.check_all.return_value = {"status": "down"}
            mock_get.return_value = agg
            resp = await health_mod.components_health(mode="fast")
        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_exception(self) -> None:
        with patch(
            "src.backend.core.di.providers.get_health_aggregator_provider"
        ) as mock_get:
            mock_get.side_effect = RuntimeError("fail")
            resp = await health_mod.components_health(mode="fast")
        assert resp.status_code == 503
