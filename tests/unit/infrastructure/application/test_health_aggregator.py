"""Unit tests for src.backend.infrastructure.application.health_aggregator."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.infrastructure.application.health_aggregator import (
    HealthAggregator,
    get_health_aggregator,
)


@pytest.fixture(autouse=True)
def _reset_singleton() -> Iterator[None]:
    """Reset module-level singleton before each test."""
    import src.backend.infrastructure.application.health_aggregator as _mod

    _mod._aggregator = None
    yield
    _mod._aggregator = None


class TestRegistration:
    def test_register_unregister_list(self) -> None:
        ha = HealthAggregator()
        async def check() -> dict[str, Any]:
            return {"status": "ok"}

        ha.register("redis", check)
        assert ha.list_components() == ["redis"]
        ha.unregister("redis")
        assert ha.list_components() == []

    def test_include_registry(self) -> None:
        ha = HealthAggregator()
        assert not ha._include_registry
        ha.include_registry(True)
        assert ha._include_registry
        ha.include_registry(False)
        assert not ha._include_registry


class TestSupportsModeKwarg:
    def test_true(self) -> None:
        async def check(*, mode: str) -> dict[str, Any]:
            return {"status": "ok"}

        assert HealthAggregator._supports_mode_kwarg(check) is True

    def test_false(self) -> None:
        async def check() -> dict[str, Any]:
            return {"status": "ok"}

        assert HealthAggregator._supports_mode_kwarg(check) is False

    def test_exception_returns_false(self) -> None:
        assert HealthAggregator._supports_mode_kwarg("not callable") is False


@pytest.mark.asyncio
class TestSafeCheck:
    async def test_success_with_mode(self) -> None:
        ha = HealthAggregator()
        async def check(*, mode: str) -> dict[str, Any]:
            return {"status": "ok", "mode": mode}

        ha.register("db", check)
        result = await ha._safe_check("db", check, mode="fast")
        assert result["status"] == "ok"
        assert result["mode"] == "fast"
        assert result["name"] == "db"

    async def test_success_without_mode(self) -> None:
        ha = HealthAggregator()
        async def check() -> dict[str, Any]:
            return {"status": "ok"}

        ha.register("db", check)
        result = await ha._safe_check("db", check, mode="deep")
        assert result["status"] == "ok"
        assert result["mode"] == "deep"
        assert result["name"] == "db"

    async def test_timeout(self) -> None:
        ha = HealthAggregator()
        async def check() -> dict[str, Any]:
            await asyncio.sleep(10)
            return {"status": "ok"}

        ha.register("slow", check)
        result = await ha._safe_check("slow", check, mode="fast")
        assert result["status"] == "error"
        assert "Timeout" in result["error"]

    async def test_exception(self) -> None:
        ha = HealthAggregator()
        async def check() -> dict[str, Any]:
            raise RuntimeError("boom")

        ha.register("bad", check)
        result = await ha._safe_check("bad", check, mode="fast")
        assert result["status"] == "error"
        assert "boom" in result["error"]

    async def test_invalid_result_type(self) -> None:
        ha = HealthAggregator()
        async def check() -> str:
            return "not a dict"

        ha.register("weird", check)
        result = await ha._safe_check("weird", check, mode="fast")
        assert result["status"] == "error"
        assert "Invalid result type" in result["error"]


@pytest.mark.asyncio
class TestCollectRegistryComponents:
    async def test_disabled(self) -> None:
        ha = HealthAggregator()
        ha.include_registry(False)
        assert await ha._collect_registry_components("fast") == {}

    async def test_empty_registry(self) -> None:
        ha = HealthAggregator()
        ha.include_registry(True)
        with patch(
            "src.backend.infrastructure.registry.ConnectorRegistry"
        ) as mock_cls:
            inst = MagicMock()
            inst.names.return_value = []
            mock_cls.instance.return_value = inst
            assert await ha._collect_registry_components("fast") == {}

    async def test_success(self) -> None:
        from src.backend.infrastructure.clients.base_connector import HealthResult

        ha = HealthAggregator()
        ha.include_registry(True)
        with patch(
            "src.backend.infrastructure.registry.ConnectorRegistry"
        ) as mock_cls:
            inst = MagicMock()
            inst.names.return_value = ["redis"]
            inst.health_all = AsyncMock(
                return_value={
                    "redis": HealthResult.ok(latency_ms=2.0, mode="fast", connections=5)
                }
            )
            mock_cls.instance.return_value = inst
            result = await ha._collect_registry_components("fast")
        assert result["redis"]["status"] == "ok"
        assert result["redis"]["latency_ms"] == 2.0
        assert result["redis"]["mode"] == "fast"
        assert result["redis"]["details"]["connections"] == 5

    async def test_registry_health_all_exception(self) -> None:
        ha = HealthAggregator()
        ha.include_registry(True)
        with patch(
            "src.backend.infrastructure.registry.ConnectorRegistry"
        ) as mock_cls:
            inst = MagicMock()
            inst.names.return_value = ["redis"]
            inst.health_all = AsyncMock(side_effect=RuntimeError("down"))
            mock_cls.instance.return_value = inst
            assert await ha._collect_registry_components("fast") == {}


@pytest.mark.asyncio
class TestCheckAll:
    async def test_empty(self) -> None:
        ha = HealthAggregator()
        result = await ha.check_all(mode="fast")
        assert result["status"] == "ok"
        assert result["components"] == {}
        assert "No health checks" in result["message"]

    async def test_legacy_only(self) -> None:
        ha = HealthAggregator()
        async def ok_check() -> dict[str, Any]:
            return {"status": "ok"}

        ha.register("svc", ok_check)
        result = await ha.check_all(mode="fast")
        assert result["status"] == "ok"
        assert result["components"]["svc"]["status"] == "ok"

    async def test_mixed_status_down(self) -> None:
        ha = HealthAggregator()
        async def ok_check() -> dict[str, Any]:
            return {"status": "ok"}

        async def err_check() -> dict[str, Any]:
            return {"status": "error", "error": "fail"}

        ha.register("a", ok_check)
        ha.register("b", err_check)
        result = await ha.check_all(mode="fast")
        assert result["status"] == "down"

    async def test_mixed_status_degraded(self) -> None:
        ha = HealthAggregator()
        async def ok_check() -> dict[str, Any]:
            return {"status": "ok"}

        async def deg_check() -> dict[str, Any]:
            return {"status": "degraded"}

        ha.register("a", ok_check)
        ha.register("b", deg_check)
        result = await ha.check_all(mode="fast")
        assert result["status"] == "degraded"

    async def test_registry_override_legacy(self) -> None:
        ha = HealthAggregator()
        ha.include_registry(True)
        async def legacy_check() -> dict[str, Any]:
            return {"status": "ok", "custom": True}

        ha.register("redis", legacy_check)
        with patch(
            "src.backend.infrastructure.registry.ConnectorRegistry"
        ) as mock_cls:
            inst = MagicMock()
            inst.names.return_value = ["redis"]
            from src.backend.infrastructure.clients.base_connector import HealthResult

            inst.health_all = AsyncMock(
                return_value={
                    "redis": HealthResult.ok(latency_ms=1.0, mode="fast")
                }
            )
            mock_cls.instance.return_value = inst
            result = await ha.check_all(mode="fast")
        # legacy overrides registry
        assert result["components"]["redis"]["custom"] is True

    async def test_publish_transition(self) -> None:
        ha = HealthAggregator()
        ha._last_overall = "ok"
        async def bad() -> dict[str, Any]:
            return {"status": "error", "error": "x"}

        ha.register("x", bad)
        with patch.object(ha, "_maybe_publish_transition", new=AsyncMock()) as mock_pub:
            await ha.check_all(mode="fast")
        mock_pub.assert_awaited_once()
        assert mock_pub.call_args[0][0] == "down"


@pytest.mark.asyncio
class TestCheckSingle:
    async def test_legacy_found(self) -> None:
        ha = HealthAggregator()
        async def check() -> dict[str, Any]:
            return {"status": "ok"}

        ha.register("svc", check)
        result = await ha.check_single("svc", mode="fast")
        assert result["status"] == "ok"

    async def test_legacy_not_found_and_registry_disabled(self) -> None:
        ha = HealthAggregator()
        result = await ha.check_single("svc", mode="fast")
        assert result["status"] == "error"
        assert "not registered" in result["error"]

    async def test_registry_found(self) -> None:
        ha = HealthAggregator()
        ha.include_registry(True)
        with patch(
            "src.backend.infrastructure.registry.ConnectorRegistry"
        ) as mock_cls:
            inst = MagicMock()
            client = MagicMock()
            from src.backend.infrastructure.clients.base_connector import HealthResult

            client.health = AsyncMock(
                return_value=HealthResult.ok(latency_ms=3.0, mode="fast")
            )
            inst.get.return_value = client
            mock_cls.instance.return_value = inst
            result = await ha.check_single("redis", mode="fast")
        assert result["status"] == "ok"
        assert result["latency_ms"] == 3.0

    async def test_registry_not_found(self) -> None:
        ha = HealthAggregator()
        ha.include_registry(True)
        with patch(
            "src.backend.infrastructure.registry.ConnectorRegistry"
        ) as mock_cls:
            inst = MagicMock()
            inst.get = MagicMock(side_effect=Exception("not found"))
            mock_cls.instance.return_value = inst
            result = await ha.check_single("redis", mode="fast")
        assert result["status"] == "error"
        assert "not registered" in result["error"]

    async def test_registry_health_error(self) -> None:
        ha = HealthAggregator()
        ha.include_registry(True)
        with patch(
            "src.backend.infrastructure.registry.ConnectorRegistry"
        ) as mock_cls:
            inst = MagicMock()
            client = MagicMock()
            client.health = AsyncMock(side_effect=RuntimeError("boom"))
            inst.get.return_value = client
            mock_cls.instance.return_value = inst
            result = await ha.check_single("redis", mode="fast")
        assert result["status"] == "error"
        assert "boom" in result["error"]


class TestGetHealthAggregator:
    def test_singleton(self) -> None:
        a1 = get_health_aggregator()
        a2 = get_health_aggregator()
        assert a1 is a2
        assert isinstance(a1, HealthAggregator)
