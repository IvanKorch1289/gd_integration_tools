"""Unit-тесты ResultUnwrapProcessor — Wave [wave:s5/k3-w12-result-monad]."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.core.config.features import feature_flags
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.result_unwrap import ResultUnwrapProcessor


def _ex(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


@pytest.fixture(autouse=True)
def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "result_unwrap_processor", True)


@pytest.mark.asyncio
async def test_ok_unwrap() -> None:
    pytest.importorskip("result")
    from result import Ok

    proc = ResultUnwrapProcessor(source="body.r", to="body.value")
    ex = _ex({"r": Ok(42)})
    await proc.process(ex, AsyncMock())
    assert ex.in_message.body["value"] == 42


@pytest.mark.asyncio
async def test_err_dlq() -> None:
    pytest.importorskip("result")
    from result import Err

    proc = ResultUnwrapProcessor(source="body.r", on_err="dlq")
    ex = _ex({"r": Err("oops")})
    await proc.process(ex, AsyncMock())
    assert ex.properties.get("_dlq") is True
    assert "oops" in str(ex.properties.get("_err"))


@pytest.mark.asyncio
async def test_skipped_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "result_unwrap_processor", False)
    proc = ResultUnwrapProcessor(source="body.r")
    ex = _ex({"r": "any"})
    await proc.process(ex, AsyncMock())
    assert ex.properties.get("result_unwrap_status") == "skipped"
