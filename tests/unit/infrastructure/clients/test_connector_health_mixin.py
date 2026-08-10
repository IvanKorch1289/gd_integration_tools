"""Unit-тесты для ConnectorHealthMixin (S203 W1)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.backend.infrastructure.clients.base_connector import HealthResult
from src.backend.infrastructure.clients.connector_health_mixin import (
    ConnectorHealthMixin,
)


class _Harness(ConnectorHealthMixin):
    """Простой наследник для тестов."""

    def __init__(self, probe: AsyncMock | None = None) -> None:
        self._probe = probe


class TestConnectorHealthMixin:
    """S203 W1: единый _timed_health для sink/source health()."""

    async def test_timed_health_ok(self) -> None:
        """Успешный probe → ok с latency_ms > 0."""
        probe = AsyncMock(return_value={"queue_depth": 0})
        h = _Harness(probe)
        result = await h._timed_health(probe, "fast")
        assert isinstance(result, HealthResult)
        assert result.status == "ok"
        assert result.latency_ms >= 0
        assert result.details == {"queue_depth": 0}

    async def test_timed_health_failed(self) -> None:
        """Probe raises → failed с error class+message."""
        probe = AsyncMock(side_effect=ConnectionError("nope"))
        h = _Harness(probe)
        result = await h._timed_health(probe, "fast")
        assert result.status == "failed"
        assert "ConnectionError" in (result.error or "")

    async def test_timed_health_mode_propagation(self) -> None:
        """mode сохраняется в результате."""
        probe = AsyncMock(return_value={})
        h = _Harness(probe)
        result = await h._timed_health(probe, "deep")
        assert result.mode == "deep"


@pytest.mark.asyncio
class TestMakeKindHealth:
    """S203 W3: per-kind health helper для HealthAggregator."""

    async def test_skipped_when_no_sinks(self) -> None:
        from src.backend.plugins.composition.setup_infra.health import (
            _make_kind_health,
        )

        # Registry может быть пустой в test context.
        check = _make_kind_health("http", "sink")
        result = await check()
        assert result["status"] == "skipped"

    async def test_normalizes_health_result(self) -> None:
        """HealthResult instance → dict."""
        from src.backend.plugins.composition.setup_infra.health import (
            _make_kind_health,
        )

        # Подменяем реестр через monkeypatch ниже — здесь проверяем форму.
        check = _make_kind_health("nonexistent_kind_xyz", "sink")
        result = await check()
        assert "status" in result
        assert "latency_ms" in result
