"""Tests for dsl/orchestration primitives."""

from __future__ import annotations

import asyncio
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.orchestration import Backfill, DryRun, HumanApproval, Sensor


class TestSensor:
    @pytest.mark.asyncio
    async def test_start_and_stop(self) -> None:
        pred = AsyncMock(return_value=False)
        sensor = Sensor(name="s1", predicate=pred, interval_seconds=0.01, route_id="r1")
        registry = MagicMock()
        registry.create_task = MagicMock(
            return_value=asyncio.create_task(asyncio.sleep(0))
        )
        with patch(
            "src.backend.dsl.orchestration.get_task_registry", return_value=registry
        ):
            await sensor.start()
        assert sensor._task is not None
        await sensor.stop()
        assert sensor._task is None


class TestBackfill:
    @pytest.mark.asyncio
    async def test_run(self) -> None:
        bf = Backfill(
            route_id="r1",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 3),
            step_days=1,
        )
        mock_dsl = MagicMock()
        mock_dsl.dispatch = AsyncMock(return_value="ok")
        with patch("src.backend.dsl.service.get_dsl_service", return_value=mock_dsl):
            results = await bf.run(lambda d: {"day": d.isoformat()})
        assert len(results) == 3
        assert mock_dsl.dispatch.await_count == 3


class TestDryRun:
    @pytest.mark.asyncio
    async def test_run(self) -> None:
        dr = DryRun(route_id="r1")
        mock_dsl = MagicMock()
        mock_dsl.dispatch = AsyncMock(return_value={"dry": True})
        with patch("src.backend.dsl.service.get_dsl_service", return_value=mock_dsl):
            result = await dr.run({"x": 1})
        mock_dsl.dispatch.assert_awaited_once_with(
            route_id="r1", body={"x": 1}, headers={"x-dry-run": "1"}
        )
        assert result == {"dry": True}


class TestHumanApproval:
    def test_approve(self) -> None:
        ha = HumanApproval(approval_id="a1", approvers=["u1"])
        ha.approve()
        assert ha.decision == "approved"
        assert ha.decided_at is not None
        assert ha.approved.is_set()

    def test_reject(self) -> None:
        ha = HumanApproval(approval_id="a1", approvers=["u1"])
        ha.reject()
        assert ha.decision == "rejected"
        assert ha.approved.is_set()

    @pytest.mark.asyncio
    async def test_wait_approved(self) -> None:
        ha = HumanApproval(approval_id="a1", approvers=["u1"])
        ha.approve()
        result = await ha.wait()
        assert result == "approved"

    @pytest.mark.asyncio
    async def test_wait_timeout(self) -> None:
        ha = HumanApproval(approval_id="a1", approvers=["u1"])
        result = await ha.wait(timeout=0.01)
        assert result == "rejected_timeout"
