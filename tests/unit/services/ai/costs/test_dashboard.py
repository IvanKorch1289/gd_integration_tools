"""Unit-тесты AICostDashboard (K4 S6 W3)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from src.backend.services.ai.costs import (
    AICostDashboard,
    CostByTenant,
    DashboardSnapshot,
    UsageByModel,
)
from src.backend.services.ai.costs.langfuse_reader import CostRow, LangFuseReader


class _StubReader(LangFuseReader):
    """Тестовый reader: возвращает фиксированный набор CostRow по group_by."""

    def __init__(self, rows_by_group: dict[str, list[CostRow]]) -> None:
        super().__init__(client=object())
        self._rows = rows_by_group

    async def fetch_costs(
        self,
        *,
        window: timedelta = timedelta(hours=24),
        group_by: str = "route",
        top_n: int = 10,
    ) -> list[CostRow]:
        return list(self._rows.get(group_by, []))


def _force_flag(monkeypatch: pytest.MonkeyPatch, value: bool) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_cost_dashboard_strict", value, raising=False)


@pytest.mark.asyncio
async def test_dashboard_disabled_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_flag(monkeypatch, False)
    dashboard = AICostDashboard()
    snap = await dashboard.snapshot()
    assert isinstance(snap, DashboardSnapshot)
    assert snap.backend == "disabled"
    assert snap.by_model == []
    assert snap.by_tenant == []


@pytest.mark.asyncio
async def test_dashboard_snapshot_aggregates(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_flag(monkeypatch, True)
    rows_by_group = {
        "provider": [
            CostRow(
                key="openai",
                requests=100,
                prompt_tokens=10000,
                completion_tokens=5000,
                total_cost_usd=0.55,
            ),
            CostRow(
                key="anthropic",
                requests=50,
                prompt_tokens=8000,
                completion_tokens=4000,
                total_cost_usd=0.42,
            ),
        ],
        "tenant": [
            CostRow(
                key="t1",
                requests=120,
                prompt_tokens=18000,
                completion_tokens=9000,
                total_cost_usd=0.85,
            ),
            CostRow(
                key="t2",
                requests=30,
                prompt_tokens=2000,
                completion_tokens=1000,
                total_cost_usd=0.12,
            ),
        ],
    }
    dashboard = AICostDashboard(reader=_StubReader(rows_by_group))
    snap = await dashboard.snapshot(window_hours=24, top_n=10)

    assert snap.backend == "langfuse"
    assert len(snap.by_model) == 2
    assert {m.model for m in snap.by_model} == {"openai", "anthropic"}
    assert len(snap.by_tenant) == 2
    # Share должен суммироваться к 1.0.
    total_share = sum(t.share for t in snap.by_tenant)
    assert total_share == pytest.approx(1.0, rel=1e-3)
    # Trend buckets — 12 штук.
    assert len(snap.token_trends) == 12


@pytest.mark.asyncio
async def test_dashboard_filters_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_flag(monkeypatch, True)
    rows_by_group: dict[str, list[CostRow]] = {
        "provider": [],
        "tenant": [
            CostRow(key="t1", requests=10, total_cost_usd=1.0),
            CostRow(key="t2", requests=20, total_cost_usd=2.0),
        ],
    }
    dashboard = AICostDashboard(reader=_StubReader(rows_by_group))
    snap = await dashboard.snapshot(tenant_id="t1")
    assert len(snap.by_tenant) == 1
    assert snap.by_tenant[0].tenant_id == "t1"


@pytest.mark.asyncio
async def test_dashboard_filters_model(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_flag(monkeypatch, True)
    rows_by_group = {
        "provider": [
            CostRow(key="openai", requests=1, total_cost_usd=0.1),
            CostRow(key="anthropic", requests=1, total_cost_usd=0.2),
        ],
        "tenant": [],
    }
    dashboard = AICostDashboard(reader=_StubReader(rows_by_group))
    snap = await dashboard.snapshot(model_filter="openai")
    assert len(snap.by_model) == 1
    assert snap.by_model[0].model == "openai"


def test_usage_by_model_to_dict() -> None:
    row = UsageByModel(
        model="gpt-4",
        requests=10,
        prompt_tokens=100,
        completion_tokens=50,
        total_cost_usd=0.5,
    )
    d = row.to_dict()
    assert d["model"] == "gpt-4"
    assert d["total_cost_usd"] == 0.5


def test_cost_by_tenant_share_default() -> None:
    row = CostByTenant(tenant_id="t", requests=1, total_cost_usd=1.0)
    assert row.share == 0.0


@pytest.mark.asyncio
async def test_dashboard_handles_reader_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_flag(monkeypatch, True)

    class _BrokenReader(LangFuseReader):
        async def fetch_costs(self, **kwargs: Any) -> list[CostRow]:  # type: ignore[override]
            raise RuntimeError("boom")

    dashboard = AICostDashboard(reader=_BrokenReader(client=object()))
    snap = await dashboard.snapshot()
    # Exception в reader не должен ломать snapshot.
    assert isinstance(snap, DashboardSnapshot)
    assert snap.by_model == []
    assert snap.by_tenant == []
