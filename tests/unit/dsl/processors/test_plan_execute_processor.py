"""Unit tests for PlanExecuteProcessor (v17 §2.1 agentic pattern #2).

Covers:

* Basic plan→execute flow with mock LLM.
* 2-step plan from mock LLM (sequential execution).
* Multi-step execution order.
* Verifier-True → result accepted, no replan.
* Verifier-False → replan triggered, up to max_replans.
* max_steps truncation when LLM returns > max_steps.
* Empty plan from LLM → out_message.body = in_message.body.
* in_message.body is passed to planner as prompt.
* out_message.body = final output of last successful step.
* Step exception → step marked failed, other steps still run.
* Replan loop: replan() called after 1 failure.
* Async planner supported.
* Init validation: bad types, bad max_steps, bad max_replans.
* PlanResult properties exposed on exchange.
* to_spec() round-trip.
* MRO integration: PlanExecuteMixin in RouteBuilder MRO.
* Chainable: RouteBuilder.plan_execute_with_callbacks() returns self.

Run::

    .venv/bin/python -m pytest tests/unit/dsl/processors/test_plan_execute_processor.py -q --tb=short
"""

# ruff: noqa: S101

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.dsl.builders.base import RouteBuilder
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.processors.plan_execute_processor import (
    PlanExecuteMixin,
    PlanExecuteProcessor,
    PlanResult,
    PlanStep,
)

# ── Helpers ────────────────────────────────────────────────────────────


def _make_exchange(
    body: Any = "hello", headers: dict[str, Any] | None = None
) -> Exchange:
    msg = Message(body=body, headers=headers or {})
    return Exchange(in_message=msg, out_message=msg)


def _make_context() -> ExecutionContext:
    return ExecutionContext(route_id="test.route")


def _identity_planner(steps: list[PlanStep]):
    """Build an async planner returning a fixed list of steps."""

    async def _planner(prompt: str) -> list[PlanStep]:
        return list(steps)

    return _planner


def _identity_executor(mapping: dict[str, Any] | None = None):
    """Build an async executor returning ``step.params['result']`` (or mapping)."""
    mapping = mapping or {}

    async def _executor(step: PlanStep) -> Any:
        if step.step_id in mapping:
            return mapping[step.step_id]
        return step.params.get("result", step.step_id)

    return _executor


def _failing_executor(fail_step_ids: list[str], exc: Exception | None = None):
    """Executor that raises for listed step_ids."""
    exc = exc or RuntimeError("step failed")

    async def _executor(step: PlanStep) -> Any:
        if step.step_id in fail_step_ids:
            raise exc
        return step.step_id

    return _executor


def _constant_verifier(value: bool):
    """Verifier always returning ``value``."""

    async def _v(result: PlanResult) -> bool:
        return value

    return _v


# ── Test classes ───────────────────────────────────────────────────────


class TestPlanStepDataclass:
    """PlanStep is a frozen dataclass."""

    def test_step_id_required(self) -> None:
        s = PlanStep(step_id="s1", action="call_tool")
        assert s.step_id == "s1"
        assert s.action == "call_tool"
        assert s.params == {}
        assert s.depends_on == []

    def test_step_frozen(self) -> None:
        s = PlanStep(step_id="s1", action="x")
        with pytest.raises((AttributeError, TypeError)):
            s.step_id = "s2"  # type: ignore[misc]

    def test_step_with_params(self) -> None:
        s = PlanStep(
            step_id="s1",
            action="call_tool",
            params={"url": "http://x"},
            depends_on=["s0"],
        )
        assert s.params == {"url": "http://x"}
        assert s.depends_on == ["s0"]


class TestPlanResultDataclass:
    """PlanResult defaults."""

    def test_result_defaults(self) -> None:
        r = PlanResult(steps_planned=[])
        assert r.steps_executed == []
        assert r.steps_succeeded == 0
        assert r.steps_failed == 0
        assert r.final_output is None
        assert r.replans == 0
        assert r.verified is None
        assert r.duration_ms == 0.0

    def test_result_is_mutable(self) -> None:
        r = PlanResult(steps_planned=[])
        r.steps_succeeded = 5
        r.replans = 2
        assert r.steps_succeeded == 5
        assert r.replans == 2


class TestPlanExecuteInit:
    """__init__ validation."""

    async def test_init_minimal(self) -> None:
        p = PlanExecuteProcessor(
            planner=_identity_planner([]), executor=_identity_executor()
        )
        assert p._max_steps == 10
        assert p._max_replans == 2
        assert p._verifier is None
        assert p.name == "plan_execute"

    async def test_init_custom_name(self) -> None:
        p = PlanExecuteProcessor(
            planner=_identity_planner([]),
            executor=_identity_executor(),
            name="my_agent",
        )
        assert p.name == "my_agent"

    async def test_init_invalid_max_steps(self) -> None:
        with pytest.raises(ValueError, match="max_steps"):
            PlanExecuteProcessor(
                planner=_identity_planner([]),
                executor=_identity_executor(),
                max_steps=0,
            )

    async def test_init_invalid_max_replans(self) -> None:
        with pytest.raises(ValueError, match="max_replans"):
            PlanExecuteProcessor(
                planner=_identity_planner([]),
                executor=_identity_executor(),
                max_replans=-1,
            )

    async def test_init_non_callable_planner(self) -> None:
        with pytest.raises(TypeError, match="planner"):
            PlanExecuteProcessor(planner="not a func", executor=_identity_executor())  # type: ignore[arg-type]

    async def test_init_non_callable_executor(self) -> None:
        with pytest.raises(TypeError, match="executor"):
            PlanExecuteProcessor(planner=_identity_planner([]), executor=42)  # type: ignore[arg-type]


class TestPlanBasic:
    """Core plan→execute flow."""

    async def test_plan_basic(self) -> None:
        async def mock_planner(prompt: str) -> list[PlanStep]:
            return [PlanStep(step_id="s1", action="echo", params={"msg": prompt})]

        async def mock_executor(step: PlanStep) -> Any:
            return step.params["msg"]

        p = PlanExecuteProcessor(planner=mock_planner, executor=mock_executor)
        ex = _make_exchange("hello")
        await p.process(ex, _make_context())
        assert ex.out_message is not None
        assert ex.out_message.body == "hello"

    async def test_plan_with_mock_llm(self) -> None:
        """2-step plan from mock LLM, both executed."""

        async def llm(prompt: str) -> list[PlanStep]:
            return [
                PlanStep(step_id="s1", action="call_tool", params={"result": 10}),
                PlanStep(step_id="s2", action="transform", params={"result": 20}),
            ]

        async def exec_tool(step: PlanStep) -> Any:
            return step.params["result"]

        p = PlanExecuteProcessor(planner=llm, executor=exec_tool)
        ex = _make_exchange("go")
        await p.process(ex, _make_context())
        assert ex.out_message.body == 20
        result = ex.get_property("plan_result")
        assert isinstance(result, PlanResult)
        assert result.steps_succeeded == 2
        assert result.steps_failed == 0
        assert result.replans == 0

    async def test_execute_steps_in_order(self) -> None:
        """Steps executed sequentially, last output = final_output."""
        call_order: list[str] = []

        async def llm(prompt: str) -> list[PlanStep]:
            return [
                PlanStep(step_id="a", action="x"),
                PlanStep(step_id="b", action="x"),
                PlanStep(step_id="c", action="x"),
            ]

        async def exec_step(step: PlanStep) -> Any:
            call_order.append(step.step_id)
            return step.step_id + "-out"

        p = PlanExecuteProcessor(planner=llm, executor=exec_step)
        ex = _make_exchange("go")
        await p.process(ex, _make_context())
        assert call_order == ["a", "b", "c"]
        assert ex.out_message.body == "c-out"
        result = ex.get_property("plan_result")
        assert [s["step_id"] for s in result.steps_executed] == ["a", "b", "c"]


class TestPlanVerifier:
    """Verifier semantics."""

    async def test_verify_passes(self) -> None:
        """Verifier True → result accepted, no replan."""
        planner = AsyncMock(return_value=[PlanStep(step_id="s1", action="x")])
        executor = AsyncMock(return_value="ok")

        p = PlanExecuteProcessor(
            planner=planner, executor=executor, verifier=_constant_verifier(True)
        )
        ex = _make_exchange("x")
        await p.process(ex, _make_context())
        result = ex.get_property("plan_result")
        assert result.verified is True
        assert result.replans == 0
        assert ex.out_message.body == "ok"
        # Planner called once (no replan).
        assert planner.await_count == 1

    async def test_verify_fails_triggers_replan(self) -> None:
        """Verifier False → replan called."""
        plans = [
            [PlanStep(step_id="s1", action="x", params={"r": "first"})],
            [PlanStep(step_id="s2", action="x", params={"r": "second"})],
            [PlanStep(step_id="s3", action="x", params={"r": "third"})],
        ]  # 3 plans: original + 2 replans
        planner = AsyncMock(side_effect=plans)
        executor = AsyncMock(side_effect=["first", "second", "third"])

        p = PlanExecuteProcessor(
            planner=planner, executor=executor, verifier=_constant_verifier(False)
        )
        ex = _make_exchange("go")
        await p.process(ex, _make_context())
        result = ex.get_property("plan_result")
        assert result.verified is False
        assert result.replans == 2  # max_replans
        assert planner.await_count == 3  # original + 2 replans

    async def test_replan_after_failure(self) -> None:
        """After 1 failure, replan called and executed."""
        plans = [
            [PlanStep(step_id="s1", action="x", params={"r": "first"})],
            [PlanStep(step_id="s2", action="x", params={"r": "second"})],
        ]
        planner = AsyncMock(side_effect=plans)
        executor = AsyncMock(side_effect=["first", "second"])

        # First verifier call fails, second passes
        verifier_results = [False, True]
        verifier = AsyncMock(side_effect=verifier_results)

        p = PlanExecuteProcessor(planner=planner, executor=executor, verifier=verifier)
        ex = _make_exchange("go")
        await p.process(ex, _make_context())
        result = ex.get_property("plan_result")
        assert result.replans == 1
        assert result.verified is True
        assert verifier.await_count == 2
        assert planner.await_count == 2

    async def test_max_replans_exhausted(self) -> None:
        """When verifier keeps failing → max_replans+1 attempts, then stop."""
        plans = [
            [PlanStep(step_id="s1", action="x")],
            [PlanStep(step_id="s1", action="x")],
            [PlanStep(step_id="s1", action="x")],
        ]
        planner = AsyncMock(side_effect=plans)
        executor = AsyncMock(return_value="ok")

        p = PlanExecuteProcessor(
            planner=planner,
            executor=executor,
            verifier=_constant_verifier(False),
            max_replans=2,
        )
        ex = _make_exchange("go")
        await p.process(ex, _make_context())
        result = ex.get_property("plan_result")
        # 1 original + 2 replans = 3 attempts
        assert planner.await_count == 3
        assert result.replans == 2
        assert result.verified is False


class TestPlanLimits:
    """Plan size limits and edge cases."""

    async def test_plan_token_limit_truncates(self) -> None:
        """Plan > max_steps → truncate to max_steps."""
        steps = [PlanStep(step_id=f"s{i}", action="x") for i in range(10)]
        planner = AsyncMock(return_value=steps)
        executor = AsyncMock(return_value="ok")

        p = PlanExecuteProcessor(planner=planner, executor=executor, max_steps=3)
        ex = _make_exchange("x")
        await p.process(ex, _make_context())
        # Only 3 steps executed
        assert executor.await_count == 3

    async def test_plan_with_no_steps(self) -> None:
        """Empty plan → no execution; out_message.body = in_message.body."""
        planner = AsyncMock(return_value=[])
        executor = AsyncMock(return_value="never")

        p = PlanExecuteProcessor(planner=planner, executor=executor)
        ex = _make_exchange("original")
        await p.process(ex, _make_context())
        result = ex.get_property("plan_result")
        assert result.steps_succeeded == 0
        assert result.steps_failed == 0
        # body = in_message.body when no steps succeeded
        assert ex.out_message.body == "original"
        executor.assert_not_awaited()


class TestPlanExchangeIO:
    """Exchange in/out behavior."""

    async def test_exchange_in_message_passed_to_planner(self) -> None:
        """in_message.body becomes planner input."""
        planner = AsyncMock(return_value=[PlanStep(step_id="s1", action="x")])
        executor = AsyncMock(return_value="done")

        p = PlanExecuteProcessor(planner=planner, executor=executor)
        ex = _make_exchange("my-prompt")
        await p.process(ex, _make_context())
        # First (and only) planner call received "my-prompt"
        first_call = planner.await_args
        assert first_call is not None
        assert first_call.args[0] == "my-prompt"
        assert ex.out_message.body == "done"

    async def test_out_message_set_to_final_output(self) -> None:
        """out_message.body = final output (last successful step)."""
        planner = AsyncMock(
            return_value=[
                PlanStep(step_id="s1", action="x", params={"r": "first"}),
                PlanStep(step_id="s2", action="x", params={"r": "second"}),
            ]
        )
        executor = AsyncMock(side_effect=["first", "second"])

        p = PlanExecuteProcessor(planner=planner, executor=executor)
        ex = _make_exchange("go")
        await p.process(ex, _make_context())
        assert ex.out_message.body == "second"
        # headers copied
        assert ex.out_message.headers == {}

    async def test_out_message_headers_copied(self) -> None:
        async def planner(prompt: str) -> list[PlanStep]:
            return [PlanStep(step_id="s1", action="x")]

        async def executor(step: PlanStep) -> Any:
            return "ok"

        p = PlanExecuteProcessor(planner=planner, executor=executor)
        ex = _make_exchange("go", headers={"X-Trace": "abc"})
        await p.process(ex, _make_context())
        assert ex.out_message.headers == {"X-Trace": "abc"}


class TestPlanFailureHandling:
    """Step failure semantics."""

    async def test_failure_in_step_returns_partial(self) -> None:
        """Step fails → other steps still execute; partial result returned."""
        planner = AsyncMock(
            return_value=[
                PlanStep(step_id="s1", action="x", params={"r": "ok1"}),
                PlanStep(step_id="s2", action="x", params={"r": "ok2"}),
            ]
        )
        # s2 fails
        executor = AsyncMock(side_effect=["ok1", RuntimeError("boom")])

        p = PlanExecuteProcessor(planner=planner, executor=executor)
        ex = _make_exchange("go")
        await p.process(ex, _make_context())
        result = ex.get_property("plan_result")
        assert result.steps_succeeded == 1
        assert result.steps_failed == 1
        # final_output = last successful step (s1)
        assert ex.out_message.body == "ok1"

    async def test_step_exception_captured_in_result(self) -> None:
        planner = AsyncMock(return_value=[PlanStep(step_id="s1", action="x")])
        executor = AsyncMock(side_effect=ValueError("nope"))

        p = PlanExecuteProcessor(planner=planner, executor=executor)
        ex = _make_exchange("go")
        await p.process(ex, _make_context())
        result = ex.get_property("plan_result")
        assert result.steps_failed == 1
        rec = result.steps_executed[0]
        assert rec["ok"] is False
        assert "nope" in rec["error"]


class TestPlanAsyncSupport:
    """Async planner/executor/verifier."""

    async def test_async_planner(self) -> None:
        """Native async planner (not AsyncMock) works."""

        async def llm(prompt: str) -> list[PlanStep]:
            await asyncio.sleep(0)  # yield
            return [PlanStep(step_id="s1", action="x", params={"echo": prompt})]

        async def exec_tool(step: PlanStep) -> Any:
            return step.params["echo"]

        p = PlanExecuteProcessor(planner=llm, executor=exec_tool)
        ex = _make_exchange("from-llm")
        await p.process(ex, _make_context())
        assert ex.out_message.body == "from-llm"

    async def test_async_verifier(self) -> None:
        async def llm(prompt: str) -> list[PlanStep]:
            return [PlanStep(step_id="s1", action="x", params={"r": "ok"})]

        async def exec_tool(step: PlanStep) -> Any:
            return step.params["r"]

        async def verifier(result: PlanResult) -> bool:
            await asyncio.sleep(0)
            return result.steps_failed == 0

        p = PlanExecuteProcessor(planner=llm, executor=exec_tool, verifier=verifier)
        ex = _make_exchange("go")
        await p.process(ex, _make_context())
        result = ex.get_property("plan_result")
        assert result.verified is True

    async def test_verifier_raises_treated_as_false(self) -> None:
        async def llm(prompt: str) -> list[PlanStep]:
            return [PlanStep(step_id="s1", action="x")]

        async def exec_tool(step: PlanStep) -> Any:
            return "ok"

        async def broken_verifier(result: PlanResult) -> bool:
            raise RuntimeError("verifier crash")

        p = PlanExecuteProcessor(
            planner=llm, executor=exec_tool, verifier=broken_verifier, max_replans=0
        )
        ex = _make_exchange("go")
        await p.process(ex, _make_context())
        result = ex.get_property("plan_result")
        assert result.verified is False


class TestPlanProperties:
    """exchange.properties are populated."""

    async def test_properties_populated(self) -> None:
        async def llm(prompt: str) -> list[PlanStep]:
            return [PlanStep(step_id="s1", action="x")]

        async def exec_tool(step: PlanStep) -> Any:
            return "ok"

        p = PlanExecuteProcessor(planner=llm, executor=exec_tool)
        ex = _make_exchange("go")
        await p.process(ex, _make_context())
        assert ex.get_property("plan_result") is not None
        assert ex.get_property("plan_replans") == 0
        assert ex.get_property("plan_steps_succeeded") == 1
        assert ex.get_property("plan_steps_failed") == 0


class TestPlanToSpec:
    """to_spec round-trip."""

    def test_to_spec(self) -> None:
        p = PlanExecuteProcessor(
            planner=_identity_planner([]),
            executor=_identity_executor(),
            max_steps=5,
            max_replans=1,
        )
        spec = p.to_spec()
        assert spec is not None
        assert spec["plan_execute"]["max_steps"] == 5
        assert spec["plan_execute"]["max_replans"] == 1
        assert spec["plan_execute"]["has_verifier"] is False

    def test_to_spec_with_verifier(self) -> None:
        p = PlanExecuteProcessor(
            planner=_identity_planner([]),
            executor=_identity_executor(),
            verifier=_constant_verifier(True),
        )
        spec = p.to_spec()
        assert spec is not None
        assert spec["plan_execute"]["has_verifier"] is True


class TestMROIntegration:
    """PlanExecuteMixin wired into RouteBuilder MRO."""

    def test_mixin_in_mro(self) -> None:
        mro = [c.__name__ for c in RouteBuilder.__mro__]
        assert "PlanExecuteMixin" in mro, f"PlanExecuteMixin not in MRO: {mro}"

    def test_plan_execute_method_exists(self) -> None:
        assert hasattr(RouteBuilder, "plan_execute")

    def test_chainable(self) -> None:
        async def llm(p: str) -> list[PlanStep]:
            return [PlanStep(step_id="s1", action="x")]

        async def ex_fn(step: PlanStep) -> Any:
            return "ok"

        b = RouteBuilder(route_id="t", source="t").plan_execute_with_callbacks(
            planner=llm, executor=ex_fn
        )
        assert isinstance(b, RouteBuilder)
        assert len(b._processors) == 1
        assert isinstance(b._processors[0], PlanExecuteProcessor)

    def test_chainable_returns_same_type(self) -> None:
        async def llm(p: str) -> list[PlanStep]:
            return []

        async def ex_fn(step: PlanStep) -> Any:
            return None

        b = RouteBuilder(route_id="t", source="t")
        result = b.plan_execute_with_callbacks(
            planner=llm, executor=ex_fn, max_steps=5, max_replans=1
        )
        assert isinstance(result, RouteBuilder)
        assert result is b  # _add returns self

    def test_mixin_class_exists_separately(self) -> None:
        """PlanExecuteMixin is importable as standalone class."""
        assert PlanExecuteMixin is not None
        assert hasattr(PlanExecuteMixin, "plan_execute_with_callbacks")
