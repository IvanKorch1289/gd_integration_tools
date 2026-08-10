"""Tests for HealthAdapter."""
from __future__ import annotations

import pytest

from src.backend.infrastructure.clients.health_adapter import HealthAdapter


@pytest.mark.unit
async def test_adapter_wraps_health_bool_ok() -> None:
    class LegacySource:
        async def health(self) -> bool:
            return True
    adapter = HealthAdapter(name="legacy_src", target=LegacySource())
    result = await adapter.health(mode="fast")
    assert result.status == "ok"
    assert result.mode == "fast"


@pytest.mark.unit
async def test_adapter_wraps_health_bool_failed() -> None:
    class LegacySource:
        async def health(self) -> bool:
            return False
    adapter = HealthAdapter(name="legacy_src", target=LegacySource())
    result = await adapter.health(mode="fast")
    assert result.status == "failed"


@pytest.mark.unit
async def test_adapter_wraps_healthcheck_method() -> None:
    class LegacyStorage:
        async def healthcheck(self) -> bool:
            return True
    adapter = HealthAdapter(name="legacy_storage", target=LegacyStorage())
    result = await adapter.health(mode="deep")
    assert result.status == "ok"
    assert result.mode == "deep"


@pytest.mark.unit
async def test_adapter_no_health_method() -> None:
    class NoHealth:
        pass
    adapter = HealthAdapter(name="no_health", target=NoHealth())
    result = await adapter.health(mode="fast")
    assert result.status == "failed"
    assert "No health method" in (result.error or "")


@pytest.mark.unit
async def test_adapter_wraps_exception() -> None:
    class BrokenSource:
        async def health(self) -> bool:
            raise ConnectionError("DNS failed")
    adapter = HealthAdapter(name="broken", target=BrokenSource())
    result = await adapter.health(mode="fast")
    assert result.status == "failed"
    assert "ConnectionError" in (result.error or "")


@pytest.mark.unit
async def test_adapter_lifecycle() -> None:
    adapter = HealthAdapter(name="test", target=object())
    await adapter.start()
    assert adapter._started is True
    await adapter.stop()
    assert adapter._started is False
