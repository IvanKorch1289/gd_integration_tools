"""Unit-тесты WorkflowCostEstimator — Sprint 12 K3 W3.

Сценарии:
    * empty history → defaults;
    * rich history → корректные p50/p95;
    * CH unavailable → graceful defaults (без exception);
    * input_size_bytes scaling;
    * estimate возвращает CostEstimate dataclass.
"""

# ruff: noqa: S101

from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.services.workflows.cost_estimator import (
    CostEstimate,
    WorkflowCostEstimator,
)


def _make_ch_result(rows: list[tuple[Any, ...]]) -> Any:
    res = MagicMock()
    res.result_rows = rows
    return res


@pytest.mark.asyncio
async def test_estimate_with_empty_history_returns_defaults() -> None:
    client_mock = MagicMock()
    client_mock.query = AsyncMock(return_value=_make_ch_result([(0, None, None, None)]))

    async def factory() -> Any:
        return client_mock

    estimator = WorkflowCostEstimator(clickhouse_client_factory=factory)
    result = await estimator.estimate(
        workflow_id="wf-unknown",
        input_size_bytes=2048,
    )
    assert result.sample_size == 0
    assert result.p50_duration_ms == 0.0
    assert result.estimated_storage_bytes == 2048


@pytest.mark.asyncio
async def test_estimate_with_rich_history() -> None:
    client_mock = MagicMock()
    client_mock.query = AsyncMock(
        return_value=_make_ch_result([(150, 1000.0, 2500.0, 1024.0)])
    )

    async def factory() -> Any:
        return client_mock

    estimator = WorkflowCostEstimator(clickhouse_client_factory=factory)
    result = await estimator.estimate(
        workflow_id="wf-known",
        input_size_bytes=512,
    )
    assert result.sample_size == 150
    assert result.p50_duration_ms == 1000.0
    assert result.p95_duration_ms == 2500.0
    assert result.estimated_compute_seconds == 2.5
    assert result.estimated_storage_bytes == int(1024.0 * 150 + 512)


@pytest.mark.asyncio
async def test_estimate_ch_unavailable_returns_graceful() -> None:
    async def broken_factory() -> Any:
        raise RuntimeError("CH down")

    estimator = WorkflowCostEstimator(clickhouse_client_factory=broken_factory)
    result = await estimator.estimate(workflow_id="wf-anything")
    assert result.sample_size == 0
    assert isinstance(result, CostEstimate)


@pytest.mark.asyncio
async def test_estimate_query_failure_returns_defaults() -> None:
    client_mock = MagicMock()
    client_mock.query = AsyncMock(side_effect=RuntimeError("syntax error"))

    async def factory() -> Any:
        return client_mock

    estimator = WorkflowCostEstimator(clickhouse_client_factory=factory)
    result = await estimator.estimate(workflow_id="wf-bug")
    assert result.sample_size == 0


@pytest.mark.asyncio
async def test_estimate_returns_dataclass() -> None:
    client_mock = MagicMock()
    client_mock.query = AsyncMock(
        return_value=_make_ch_result([(10, 500.0, 800.0, 256.0)])
    )

    async def factory() -> Any:
        return client_mock

    estimator = WorkflowCostEstimator(clickhouse_client_factory=factory)
    result = await estimator.estimate(workflow_id="wf-ds")
    assert isinstance(result, CostEstimate)
    assert isinstance(result.estimated_cost_usd, Decimal)


@pytest.mark.asyncio
async def test_estimate_version_propagated() -> None:
    client_mock = MagicMock()
    client_mock.query = AsyncMock(
        return_value=_make_ch_result([(5, 100.0, 200.0, 100.0)])
    )

    async def factory() -> Any:
        return client_mock

    estimator = WorkflowCostEstimator(clickhouse_client_factory=factory)
    result = await estimator.estimate(workflow_id="wf-v", version="2.1")
    assert result.version == "2.1"
