"""Unit tests for DQCheckProcessor."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.dq_check import DQCheckProcessor


def _ex(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


@pytest.mark.asyncio
async def test_dq_check_clean() -> None:
    with patch("src.backend.services.ops.data_quality.get_dq_monitor") as mock_get:
        monitor = AsyncMock()
        monitor.check.return_value = {"is_clean": True, "violations": []}
        mock_get.return_value = monitor

        proc = DQCheckProcessor(rules=[{"name": "r1"}], dataset="test")
        exchange = _ex({"amount": 100})
        await proc.process(exchange, None)  # type: ignore[arg-type]

        assert exchange.properties["dq_result"]["is_clean"] is True
        monitor.add_rule.assert_called_once_with({"name": "r1"})


@pytest.mark.asyncio
async def test_dq_check_fail_on_violation() -> None:
    with patch("src.backend.services.ops.data_quality.get_dq_monitor") as mock_get:
        monitor = AsyncMock()
        monitor.check.return_value = {"is_clean": False, "violations": [{"rule": "r1"}]}
        mock_get.return_value = monitor

        proc = DQCheckProcessor(fail_on_violation=True)
        exchange = _ex({"amount": -1})
        await proc.process(exchange, None)  # type: ignore[arg-type]

        assert exchange.error is not None
        assert "DQ violations" in exchange.error
