"""Unit-тесты UnitConversionProcessor — Wave [wave:s5/k3-w3-processor-pack-3]."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.core.config.features import feature_flags
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.unit_conversion import UnitConversionProcessor


def _ex(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


@pytest.fixture(autouse=True)
def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "proc_unit_conversion", True)


@pytest.mark.asyncio
async def test_meter_to_foot() -> None:
    pytest.importorskip("pint")
    proc = UnitConversionProcessor(
        from_unit="meter", to_unit="foot", value=1.0, to="body.feet"
    )
    ex = _ex({})
    await proc.process(ex, AsyncMock())
    feet = ex.in_message.body["feet"]
    assert abs(feet - 3.2808) < 0.01


@pytest.mark.asyncio
async def test_value_from_body_source() -> None:
    pytest.importorskip("pint")
    proc = UnitConversionProcessor(
        from_unit="kilogram",
        to_unit="pound",
        from_value_source="body.weight",
        to="body.lb",
    )
    ex = _ex({"weight": 1.0})
    await proc.process(ex, AsyncMock())
    assert abs(ex.in_message.body["lb"] - 2.2046) < 0.01


@pytest.mark.asyncio
async def test_skipped_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "proc_unit_conversion", False)
    proc = UnitConversionProcessor(from_unit="m", to_unit="ft", value=1)
    ex = _ex({})
    await proc.process(ex, AsyncMock())
    assert ex.properties.get("unit_conversion_status") == "skipped"
