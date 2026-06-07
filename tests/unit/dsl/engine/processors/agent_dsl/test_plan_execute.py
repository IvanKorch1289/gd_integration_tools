"""Unit-тесты PlanExecuteProcessor (S39 W2)."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.agent_dsl.plan_execute import (
    PlanExecuteProcessor,
)


def _make_exchange(body: Any = None) -> Exchange[Any]:
    from src.backend.dsl.engine.exchange import ExchangeMeta

    msg = Message(body=body if body is not None else {}, headers={})
    return Exchange(in_message=msg, meta=ExchangeMeta())


class TestPlanExecuteInit:
    def test_init_minimal(self) -> None:
        proc = PlanExecuteProcessor(
            planner_workflow_id="plan",
            executor_workflow_id="exec",
            verifier_workflow_id="ver",
        )
        assert proc.planner_workflow_id == "plan"
        assert proc.executor_workflow_id == "exec"
        assert proc.verifier_workflow_id == "ver"
        assert proc.max_replans == 3
        assert proc.plan_output_property == "plan"
        assert proc.result_property == "plan_execute_result"

    def test_init_full(self) -> None:
        proc = PlanExecuteProcessor(
            planner_workflow_id="p",
            executor_workflow_id="e",
            verifier_workflow_id="v",
            max_replans=5,
            plan_output_property="my_plan",
            result_property="my_result",
            timeout_s=60.0,
            name="custom",
        )
        assert proc.max_replans == 5
        assert proc.plan_output_property == "my_plan"
        assert proc.result_property == "my_result"
        assert proc.timeout_s == 60.0
        assert proc.name == "custom"

    def test_init_missing_planner_raises(self) -> None:
        with pytest.raises(ValueError, match="planner_workflow_id"):
            PlanExecuteProcessor(
                planner_workflow_id="",
                executor_workflow_id="exec",
                verifier_workflow_id="ver",
            )

    def test_init_missing_executor_raises(self) -> None:
        with pytest.raises(ValueError, match="executor_workflow_id"):
            PlanExecuteProcessor(
                planner_workflow_id="plan",
                executor_workflow_id="",
                verifier_workflow_id="ver",
            )

    def test_init_missing_verifier_raises(self) -> None:
        with pytest.raises(ValueError, match="verifier_workflow_id"):
            PlanExecuteProcessor(
                planner_workflow_id="plan",
                executor_workflow_id="exec",
                verifier_workflow_id="",
            )


class TestPlanExecuteSuccess:
    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_single_step_success(self) -> None:
        exchange = _make_exchange()
        proc = PlanExecuteProcessor(
            planner_workflow_id="plan",
            executor_workflow_id="exec",
            verifier_workflow_id="ver",
        )

        planner_resp = _mock_response(
            structured={"steps": [{"id": "1", "description": "step1", "input": {}}]}
        )
        executor_resp = _mock_response(content="done")
        verifier_resp = _mock_response(structured={"verdict": "ok"})

        gateway = AsyncMock()
        gateway.invoke.side_effect = [planner_resp, executor_resp, verifier_resp]

        with patch.object(proc, "_resolve_gateway", return_value=gateway):
            await proc._run(exchange, AsyncMock())

        assert exchange.error is None
        result = exchange.get_property("plan_execute_result")
        assert result["status"] == "success"
        assert result["replan_count"] == 0
        assert len(result["step_results"]) == 1

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_multi_step_success(self) -> None:
        exchange = _make_exchange()
        proc = PlanExecuteProcessor(
            planner_workflow_id="plan",
            executor_workflow_id="exec",
            verifier_workflow_id="ver",
        )

        planner_resp = _mock_response(
            structured={
                "steps": [
                    {"id": "1", "description": "a", "input": {}},
                    {"id": "2", "description": "b", "input": {}},
                ]
            }
        )
        gateway = AsyncMock()
        gateway.invoke.side_effect = [
            planner_resp,
            _mock_response(content="r1"),
            _mock_response(structured={"verdict": "ok"}),
            _mock_response(content="r2"),
            _mock_response(structured={"verdict": "ok"}),
        ]

        with patch.object(proc, "_resolve_gateway", return_value=gateway):
            await proc._run(exchange, AsyncMock())

        result = exchange.get_property("plan_execute_result")
        assert result["status"] == "success"
        assert len(result["step_results"]) == 2


class TestPlanExecuteReplan:
    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_verification_fails_then_replan_success(self) -> None:
        exchange = _make_exchange()
        proc = PlanExecuteProcessor(
            planner_workflow_id="plan",
            executor_workflow_id="exec",
            verifier_workflow_id="ver",
            max_replans=1,
        )

        plan1 = {"steps": [{"id": "1", "description": "s1", "input": {}}]}
        plan2 = {"steps": [{"id": "1", "description": "s1-fixed", "input": {}}]}

        gateway = AsyncMock()
        gateway.invoke.side_effect = [
            _mock_response(structured=plan1),  # plan 1
            _mock_response(content="r1"),  # exec 1
            _mock_response(structured={"verdict": "fail", "reason": "bad"}),  # verify 1
            _mock_response(structured=plan2),  # replan
            _mock_response(content="r2"),  # exec 2
            _mock_response(structured={"verdict": "ok"}),  # verify 2
        ]

        with patch.object(proc, "_resolve_gateway", return_value=gateway):
            await proc._run(exchange, AsyncMock())

        result = exchange.get_property("plan_execute_result")
        assert result["status"] == "success"
        assert result["replan_count"] == 1

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_max_replans_exceeded(self) -> None:
        exchange = _make_exchange()
        proc = PlanExecuteProcessor(
            planner_workflow_id="plan",
            executor_workflow_id="exec",
            verifier_workflow_id="ver",
            max_replans=0,
        )

        plan = {"steps": [{"id": "1", "description": "s1", "input": {}}]}
        gateway = AsyncMock()
        gateway.invoke.side_effect = [
            _mock_response(structured=plan),
            _mock_response(content="r1"),
            _mock_response(structured={"verdict": "fail", "reason": "bad"}),
        ]

        with patch.object(proc, "_resolve_gateway", return_value=gateway):
            await proc._run(exchange, AsyncMock())

        assert exchange.error is not None
        assert "replan" in exchange.error.lower() or "исчерпаны" in exchange.error
        assert exchange.stopped


class TestPlanExecuteEdgeCases:
    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_empty_plan(self) -> None:
        exchange = _make_exchange()
        proc = PlanExecuteProcessor(
            planner_workflow_id="plan",
            executor_workflow_id="exec",
            verifier_workflow_id="ver",
        )
        gateway = AsyncMock()
        gateway.invoke.return_value = _mock_response(structured={"steps": []})

        with patch.object(proc, "_resolve_gateway", return_value=gateway):
            await proc._run(exchange, AsyncMock())

        result = exchange.get_property("plan_execute_result")
        assert result["status"] == "success"
        assert result["step_results"] == []

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_no_gateway_sets_error(self) -> None:
        exchange = _make_exchange()
        proc = PlanExecuteProcessor(
            planner_workflow_id="plan",
            executor_workflow_id="exec",
            verifier_workflow_id="ver",
        )
        with patch.object(proc, "_resolve_gateway", return_value=None):
            await proc._run(exchange, AsyncMock())
        assert exchange.error is not None
        assert "AIGateway" in exchange.error
        assert exchange.stopped

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_planner_returns_non_json(self) -> None:
        exchange = _make_exchange()
        proc = PlanExecuteProcessor(
            planner_workflow_id="plan",
            executor_workflow_id="exec",
            verifier_workflow_id="ver",
        )
        gateway = AsyncMock()
        gateway.invoke.return_value = _mock_response(content="not json")

        with patch.object(proc, "_resolve_gateway", return_value=gateway):
            await proc._run(exchange, AsyncMock())

        assert exchange.error is not None
        assert "план" in exchange.error.lower() or "plan" in exchange.error.lower()


class TestPlanExecuteToSpec:
    def test_to_spec_defaults(self) -> None:
        proc = PlanExecuteProcessor(
            planner_workflow_id="p", executor_workflow_id="e", verifier_workflow_id="v"
        )
        assert proc.to_spec() == {
            "plan_execute": {
                "planner_workflow_id": "p",
                "executor_workflow_id": "e",
                "verifier_workflow_id": "v",
            }
        }

    def test_to_spec_full(self) -> None:
        proc = PlanExecuteProcessor(
            planner_workflow_id="p",
            executor_workflow_id="e",
            verifier_workflow_id="v",
            max_replans=5,
            plan_output_property="po",
            result_property="rp",
            timeout_s=60.0,
        )
        spec = proc.to_spec()["plan_execute"]
        assert spec["max_replans"] == 5
        assert spec["plan_output_property"] == "po"
        assert spec["result_property"] == "rp"
        assert spec["timeout_s"] == 60.0


# ── helpers ──


def _mock_response(
    *, content: str = "", structured: dict[str, Any] | None = None
) -> Any:
    """Минимальный mock AIResponse."""
    resp: Any = type("_Resp", (), {})()
    resp.content = content
    resp.structured = structured
    return resp
