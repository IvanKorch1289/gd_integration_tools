"""Unit-тесты ReflectionLoopProcessor (S39 W3)."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.agent_dsl.reflection_loop import (
    ReflectionLoopProcessor,
)


def _make_exchange(body: Any = None) -> Exchange[Any]:
    from src.backend.dsl.engine.exchange import ExchangeMeta

    msg = Message(body=body if body is not None else {}, headers={})
    return Exchange(in_message=msg, meta=ExchangeMeta())


def _mock_response(
    *, content: str = "", structured: dict[str, Any] | None = None
) -> Any:
    """Минимальный mock AIResponse."""
    resp: Any = type("_Resp", (), {})()
    resp.content = content
    resp.structured = structured
    return resp


class TestReflectionLoopInit:
    def test_init_minimal(self) -> None:
        proc = ReflectionLoopProcessor(
            generator_workflow_id="gen", reflector_workflow_id="ref"
        )
        assert proc.generator_workflow_id == "gen"
        assert proc.reflector_workflow_id == "ref"
        assert proc.refiner_workflow_id == "gen"  # default fallback
        assert proc.max_iterations == 3
        assert proc.stop_verdict == "ok"
        assert proc.result_property == "reflection_result"
        assert proc.history_property == "reflection_history"

    def test_init_full(self) -> None:
        proc = ReflectionLoopProcessor(
            generator_workflow_id="gen",
            reflector_workflow_id="ref",
            refiner_workflow_id="fin",
            max_iterations=5,
            stop_verdict="approved",
            result_property="my_result",
            history_property="my_history",
            timeout_s=60.0,
            name="custom",
        )
        assert proc.refiner_workflow_id == "fin"
        assert proc.max_iterations == 5
        assert proc.stop_verdict == "approved"
        assert proc.result_property == "my_result"
        assert proc.history_property == "my_history"
        assert proc.timeout_s == 60.0
        assert proc.name == "custom"

    def test_init_missing_generator_raises(self) -> None:
        with pytest.raises(ValueError, match="generator_workflow_id"):
            ReflectionLoopProcessor(
                generator_workflow_id="", reflector_workflow_id="ref"
            )

    def test_init_missing_reflector_raises(self) -> None:
        with pytest.raises(ValueError, match="reflector_workflow_id"):
            ReflectionLoopProcessor(
                generator_workflow_id="gen", reflector_workflow_id=""
            )


class TestReflectionLoopSuccess:
    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_single_iteration_stop_verdict(self) -> None:
        exchange = _make_exchange()
        proc = ReflectionLoopProcessor(
            generator_workflow_id="gen", reflector_workflow_id="ref"
        )

        gateway = AsyncMock()
        gateway.invoke.side_effect = [
            _mock_response(structured={"draft": "initial draft"}),
            _mock_response(structured={"verdict": "ok", "critique": "perfect"}),
        ]

        with patch.object(proc, "_resolve_gateway", return_value=gateway):
            await proc._run(exchange, AsyncMock())

        assert exchange.error is None
        result = exchange.get_property("reflection_result")
        assert result["status"] == "success"
        assert result["draft"] == "initial draft"
        assert result["final_verdict"] == "ok"
        assert result["iterations"] == 1

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_reflect_then_refine_then_stop(self) -> None:
        exchange = _make_exchange()
        proc = ReflectionLoopProcessor(
            generator_workflow_id="gen",
            reflector_workflow_id="ref",
            refiner_workflow_id="fin",
            max_iterations=3,
        )

        gateway = AsyncMock()
        gateway.invoke.side_effect = [
            _mock_response(structured={"draft": "draft v1"}),
            _mock_response(structured={"verdict": "fail", "critique": "bad"}),
            _mock_response(structured={"draft": "draft v2"}),
            _mock_response(structured={"verdict": "ok", "critique": "good"}),
        ]

        with patch.object(proc, "_resolve_gateway", return_value=gateway):
            await proc._run(exchange, AsyncMock())

        result = exchange.get_property("reflection_result")
        assert result["status"] == "success"
        assert result["draft"] == "draft v2"
        assert result["iterations"] == 2

        history = exchange.get_property("reflection_history")
        assert len(history) == 4  # generate + reflect + refine + reflect
        assert history[0]["stage"] == "generate"
        assert history[1]["stage"] == "reflect"
        assert history[2]["stage"] == "refine"
        assert history[3]["stage"] == "reflect"


class TestReflectionLoopMaxIterations:
    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_max_iterations_reached(self) -> None:
        exchange = _make_exchange()
        proc = ReflectionLoopProcessor(
            generator_workflow_id="gen", reflector_workflow_id="ref", max_iterations=2
        )

        gateway = AsyncMock()
        gateway.invoke.side_effect = [
            _mock_response(structured={"draft": "draft v1"}),
            _mock_response(structured={"verdict": "fail", "critique": "bad1"}),
            _mock_response(structured={"draft": "draft v2"}),
            _mock_response(structured={"verdict": "fail", "critique": "bad2"}),
        ]

        with patch.object(proc, "_resolve_gateway", return_value=gateway):
            await proc._run(exchange, AsyncMock())

        result = exchange.get_property("reflection_result")
        assert result["status"] == "max_iterations_reached"
        assert result["draft"] == "draft v2"
        assert result["iterations"] == 2


class TestReflectionLoopEdgeCases:
    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_no_gateway_sets_error(self) -> None:
        exchange = _make_exchange()
        proc = ReflectionLoopProcessor(
            generator_workflow_id="gen", reflector_workflow_id="ref"
        )
        with patch.object(proc, "_resolve_gateway", return_value=None):
            await proc._run(exchange, AsyncMock())
        assert exchange.error is not None
        assert "AIGateway" in exchange.error
        assert exchange.stopped

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_generator_returns_none(self) -> None:
        exchange = _make_exchange()
        proc = ReflectionLoopProcessor(
            generator_workflow_id="gen", reflector_workflow_id="ref"
        )
        gateway = AsyncMock()
        gateway.invoke.return_value = None

        with patch.object(proc, "_resolve_gateway", return_value=gateway):
            await proc._run(exchange, AsyncMock())

        assert exchange.error is not None
        assert "draft" in exchange.error.lower()

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_reflector_returns_non_json_content(self) -> None:
        exchange = _make_exchange()
        proc = ReflectionLoopProcessor(
            generator_workflow_id="gen", reflector_workflow_id="ref", max_iterations=1
        )
        gateway = AsyncMock()
        gateway.invoke.side_effect = [
            _mock_response(structured={"draft": "draft"}),
            _mock_response(content="not json"),
        ]

        with patch.object(proc, "_resolve_gateway", return_value=gateway):
            await proc._run(exchange, AsyncMock())

        result = exchange.get_property("reflection_result")
        # non-JSON content yields empty verdict → not stop_verdict → max_iterations
        assert result["status"] == "max_iterations_reached"

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_reflection_fails_returns_none(self) -> None:
        exchange = _make_exchange()
        proc = ReflectionLoopProcessor(
            generator_workflow_id="gen", reflector_workflow_id="ref"
        )
        gateway = AsyncMock()
        gateway.invoke.side_effect = [
            _mock_response(structured={"draft": "draft"}),
            None,
        ]

        with patch.object(proc, "_resolve_gateway", return_value=gateway):
            await proc._run(exchange, AsyncMock())

        assert exchange.error is not None
        assert "reflection failed" in exchange.error.lower()

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_refine_fails_returns_none(self) -> None:
        exchange = _make_exchange()
        proc = ReflectionLoopProcessor(
            generator_workflow_id="gen", reflector_workflow_id="ref", max_iterations=2
        )
        gateway = AsyncMock()
        gateway.invoke.side_effect = [
            _mock_response(structured={"draft": "draft"}),
            _mock_response(structured={"verdict": "fail", "critique": "bad"}),
            None,
        ]

        with patch.object(proc, "_resolve_gateway", return_value=gateway):
            await proc._run(exchange, AsyncMock())

        assert exchange.error is not None
        assert "refine failed" in exchange.error.lower()


class TestReflectionLoopToSpec:
    def test_to_spec_defaults(self) -> None:
        proc = ReflectionLoopProcessor(
            generator_workflow_id="gen", reflector_workflow_id="ref"
        )
        assert proc.to_spec() == {
            "reflection_loop": {
                "generator_workflow_id": "gen",
                "reflector_workflow_id": "ref",
            }
        }

    def test_to_spec_full(self) -> None:
        proc = ReflectionLoopProcessor(
            generator_workflow_id="gen",
            reflector_workflow_id="ref",
            refiner_workflow_id="fin",
            max_iterations=5,
            stop_verdict="approved",
            result_property="rp",
            history_property="hp",
            timeout_s=60.0,
        )
        spec = proc.to_spec()["reflection_loop"]
        assert spec["refiner_workflow_id"] == "fin"
        assert spec["max_iterations"] == 5
        assert spec["stop_verdict"] == "approved"
        assert spec["result_property"] == "rp"
        assert spec["history_property"] == "hp"
        assert spec["timeout_s"] == 60.0

    def test_to_spec_no_history(self) -> None:
        proc = ReflectionLoopProcessor(
            generator_workflow_id="gen",
            reflector_workflow_id="ref",
            history_property=None,
        )
        spec = proc.to_spec()["reflection_loop"]
        assert spec.get("history_property") is None
