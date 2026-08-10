"""Unit tests for DQCheckProcessor."""


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


# ── Round 14 R14-5: edge-case tests ──────────────────────────────────────


@pytest.mark.asyncio
async def test_dq_check_empty_rules_is_clean() -> None:
    """Round 14 R14-5: пустой ``rules`` → result clean (no violations).

    Конструктор нормализует ``rules=None`` в ``[]`` (line 31), но
    не было теста покрывающего этот edge case.
    """
    with patch("src.backend.services.ops.data_quality.get_dq_monitor") as mock_get:
        monitor = AsyncMock()
        monitor.check.return_value = {"is_clean": True, "violations": []}
        mock_get.return_value = monitor

        proc = DQCheckProcessor(rules=None)
        exchange = _ex({"amount": 100})
        await proc.process(exchange, None)  # type: ignore[arg-type]

        assert exchange.properties["dq_result"]["is_clean"] is True
        # Никаких rule'ов не добавлено (было пусто).
        monitor.add_rule.assert_not_called()


@pytest.mark.asyncio
async def test_dq_check_none_body_handled() -> None:
    """Round 14 R14-5: ``body=None`` → monitor.check(None), не падает.

    Edge case: проверка должна выдержать пустой payload без exception.
    """
    with patch("src.backend.services.ops.data_quality.get_dq_monitor") as mock_get:
        monitor = AsyncMock()
        monitor.check.return_value = {"is_clean": True, "violations": []}
        mock_get.return_value = monitor

        proc = DQCheckProcessor(rules=[{"name": "r1"}])
        exchange = _ex(body=None)
        await proc.process(exchange, None)  # type: ignore[arg-type]

        monitor.check.assert_awaited_once_with(None, dataset="default")
        assert exchange.properties["dq_result"]["is_clean"] is True


@pytest.mark.asyncio
async def test_dq_check_violations_set_without_fail_on_violation() -> None:
    """Round 14 R14-5: violations без ``fail_on_violation=True`` → exchange OK,
    ``dq_result`` содержит violations для downstream processors.

    Гарантирует что violations видны consumer'ам даже когда не fail-fast.
    """
    with patch("src.backend.services.ops.data_quality.get_dq_monitor") as mock_get:
        monitor = AsyncMock()
        monitor.check.return_value = {
            "is_clean": False,
            "violations": [{"rule": "r1", "detail": "x < 0"}],
        }
        mock_get.return_value = monitor

        proc = DQCheckProcessor(rules=[{"name": "r1"}], fail_on_violation=False)
        exchange = _ex({"amount": -1})
        await proc.process(exchange, None)  # type: ignore[arg-type]

        assert exchange.error is None
        result = exchange.properties["dq_result"]
        assert result["is_clean"] is False
        assert result["violations"] == [{"rule": "r1", "detail": "x < 0"}]
