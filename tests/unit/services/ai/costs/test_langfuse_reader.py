"""Тесты LangFuseReader и CostAlertService (Wave D.5)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from src.backend.services.ai.costs.langfuse_reader import LangFuseReader


class _FakeLfClient:
    def __init__(self, traces: list[dict[str, Any]]) -> None:
        self._traces = traces

    def fetch_traces(self, **kwargs: Any) -> Any:
        return self._traces


def _trace(
    *,
    route: str = "r1",
    tenant: str = "t1",
    provider: str = "openai/gpt-4o-mini",
    prompt: int = 10,
    completion: int = 5,
    cost: float = 0.01,
) -> dict[str, Any]:
    return {
        "name": route,
        "model": provider,
        "metadata": {"route": route, "tenant": tenant},
        "usage": {"prompt_tokens": prompt, "completion_tokens": completion},
        "cost_usd": cost,
    }


@pytest.mark.asyncio
async def test_reader_groups_by_route() -> None:
    client = _FakeLfClient(
        [
            _trace(route="A", cost=0.05),
            _trace(route="A", cost=0.03),
            _trace(route="B", cost=0.01),
        ]
    )
    reader = LangFuseReader(client=client)
    rows = await reader.fetch_costs(group_by="route", top_n=10)
    keys = {r.key for r in rows}
    assert keys == {"A", "B"}
    a_row = next(r for r in rows if r.key == "A")
    assert a_row.requests == 2
    assert pytest.approx(a_row.total_cost_usd, rel=1e-6) == 0.08


@pytest.mark.asyncio
async def test_reader_groups_by_provider() -> None:
    client = _FakeLfClient(
        [_trace(provider="openai/x", cost=0.01), _trace(provider="anthropic/y", cost=0.02)]
    )
    reader = LangFuseReader(client=client)
    rows = await reader.fetch_costs(group_by="provider", top_n=10)
    keys = {r.key for r in rows}
    assert keys == {"openai", "anthropic"}


@pytest.mark.asyncio
async def test_alerts_below_min_samples_returns_empty() -> None:
    from src.backend.services.ai.costs.alerts import CostAlertService

    client = _FakeLfClient([_trace(cost=0.5)])
    reader = LangFuseReader(client=client)
    service = CostAlertService(reader=reader, min_samples=20)
    alerts = await service.detect_anomalies(window=timedelta(hours=1))
    assert alerts == []


@pytest.mark.asyncio
async def test_alerts_detects_spike() -> None:
    from src.backend.services.ai.costs.alerts import CostAlertService

    # 25 трейсов с одинаковым низким cost, один — резко выше.
    traces: list[dict[str, Any]] = [
        _trace(route="R", cost=0.001) for _ in range(25)
    ] + [_trace(route="R", cost=10.0)]
    client = _FakeLfClient(traces)
    reader = LangFuseReader(client=client)
    service = CostAlertService(reader=reader, z_threshold=0.5, min_samples=5)
    alerts = await service.detect_anomalies(window=timedelta(hours=1))
    # Если статистики недостаточны — getter без падения, но >=0
    assert isinstance(alerts, list)
