"""Unit-тесты GeoProcessor — Wave [wave:s5/k3-w3-processor-pack-3]."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.core.config.features import feature_flags
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.geo import GeoProcessor


def _ex(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


@pytest.fixture(autouse=True)
def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "proc_geo", True)


@pytest.mark.asyncio
async def test_distance_moscow_spb() -> None:
    pytest.importorskip("geopy")
    proc = GeoProcessor(
        mode="distance",
        point_a=(55.7558, 37.6173),
        point_b=(59.9343, 30.3351),
        to="body.dist",
    )
    ex = _ex()
    await proc.process(ex, AsyncMock())
    dist = ex.in_message.body["dist"]
    assert "km" in dist
    # MSK→SPB ≈ 633 km (geodesic)
    assert 600 < dist["km"] < 700


@pytest.mark.asyncio
async def test_skipped_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "proc_geo", False)
    proc = GeoProcessor(mode="distance", point_a=(0, 0), point_b=(1, 1), to="body.x")
    ex = _ex()
    await proc.process(ex, AsyncMock())
    assert ex.properties.get("geo_status") == "skipped"


def test_validates_constructor() -> None:
    with pytest.raises(ValueError, match="mode"):
        GeoProcessor(mode="invalid")
