"""Unit-тесты RouteRunner (через адаптер)."""

from __future__ import annotations

import pytest

from testkit.route_runner import RouteRunner


@pytest.mark.asyncio
async def test_route_runner_returns_run_result() -> None:
    """RouteRunner.run отдаёт RouteRunResult с echo-payload (fallback path)."""
    runner = RouteRunner()
    result = await runner.run("health.ping", {"x": 1})
    assert result.route_id == "health.ping"
    # 200 ожидается даже в fallback-режиме (loader не выставил invoke_route)
    assert result.status_code == 200


@pytest.mark.asyncio
async def test_route_runner_accepts_tenant_kwarg() -> None:
    """Контракт: ``tenant`` принимается как kwarg, не падает."""
    runner = RouteRunner()
    result = await runner.run("health.ping", payload=None, tenant="acme")
    assert result.route_id == "health.ping"
