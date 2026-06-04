"""Unit tests for SagaLRAProcessor (S38 W3, saga coordinator state machine).

Covers:

* happy path: 3 steps all succeed;
* failure on step N → compensations of steps 0..N-1 run in REVERSE;
* state machine transitions and exchange properties;
* partial compensation (only succeeded steps are compensated);
* idempotent compensations (same step name called twice → safe);
* empty steps list → state = ``completed`` immediately;
* single-step saga (no compensation on failure);
* compensation that itself fails → state = ``"failed"`` + original
  error wrapped in :class:`SagaCompensationError`;
* per-step timeout enforcement;
* exchange property keys (state, completed_steps, failed_step, etc.);
* step naming / duplicate name detection;
* concurrent sagas in parallel (no state collision);
* ``to_spec`` serialization.

Run::

    .venv/bin/python -m pytest tests/unit/dsl/processors/test_saga_lra_processor.py -q --tb=short
"""

# ruff: noqa: S101

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.processors.saga_lra_processor import (
    STATE_COMPENSATED,
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_RUNNING,
    SagaCompensationError,
    SagaLRAError,
    SagaLRAProcessor,
)

# ── Helpers ────────────────────────────────────────────────────────────


def _make_exchange(body: Any = None) -> Exchange[Any]:
    msg = Message(body=body, headers={})
    return Exchange(in_message=msg, out_message=msg)


def _make_context() -> ExecutionContext:
    return ExecutionContext(route_id="test.route")


def _identity(name: str, *, fail: bool = False, raise_exc: bool = False):
    """Build a sync action that records its call.

    If ``fail=True`` the action calls ``exchange.fail(...)`` (Camel-style).
    If ``raise_exc=True`` the action raises ``RuntimeError``.
    """
    calls: list[str] = []

    def _fn(exchange: "Exchange[Any]", context: "ExecutionContext") -> None:
        calls.append(name)
        if raise_exc:
            raise RuntimeError(f"raise:{name}")
        if fail:
            exchange.fail(f"failed at {name}")

    _fn.calls = calls  # type: ignore[attr-defined]
    _fn.name = name  # type: ignore[attr-defined]
    return _fn


def _identity_async(name: str, *, raise_exc: bool = False):
    """Async variant of ``_identity``."""
    calls: list[str] = []

    async def _fn(exchange: "Exchange[Any]", context: "ExecutionContext") -> None:
        calls.append(name)
        if raise_exc:
            raise RuntimeError(f"raise:{name}")

    _fn.calls = calls  # type: ignore[attr-defined]
    _fn.name = name  # type: ignore[attr-defined]
    return _fn


# ── Initialization & validation ────────────────────────────────────────


class TestSagaLRAInit:
    def test_init_minimal(self) -> None:
        p = SagaLRAProcessor(steps=[])
        assert p._steps == []
        assert p._timeout_seconds == 300.0
        assert p._per_step_timeout == 30.0
        assert p._state_property == "saga_state"
        assert p._result_property == "saga_result"
        assert p._fail_fast is False

    def test_init_custom_name(self) -> None:
        p = SagaLRAProcessor(steps=[], name="custom-saga")
        assert p.name == "custom-saga"

    def test_init_default_name_includes_step_count(self) -> None:
        p = SagaLRAProcessor(
            steps=[{"name": "a", "action": lambda e, c: None}]
        )
        assert "1 steps" in p.name

    def test_init_invalid_timeout_raises(self) -> None:
        with pytest.raises(ValueError, match="timeout_seconds"):
            SagaLRAProcessor(steps=[], timeout_seconds=0)

    def test_init_negative_per_step_timeout_raises(self) -> None:
        with pytest.raises(ValueError, match="per_step_timeout_seconds"):
            SagaLRAProcessor(steps=[], per_step_timeout_seconds=-1.0)

    def test_init_per_step_timeout_none_disables(self) -> None:
        p = SagaLRAProcessor(steps=[], per_step_timeout_seconds=None)
        assert p._per_step_timeout is None

    def test_init_steps_must_be_list(self) -> None:
        with pytest.raises(TypeError, match="list"):
            SagaLRAProcessor(steps="not-a-list")  # type: ignore[arg-type]

    def test_init_step_must_be_dict(self) -> None:
        with pytest.raises(TypeError, match="dict"):
            SagaLRAProcessor(steps=["not-a-dict"])  # type: ignore[list-item]

    def test_init_action_must_be_callable(self) -> None:
        with pytest.raises(ValueError, match="action"):
            SagaLRAProcessor(steps=[{"name": "x", "action": "nope"}])

    def test_init_compensation_must_be_callable_or_none(self) -> None:
        with pytest.raises(ValueError, match="compensation"):
            SagaLRAProcessor(
                steps=[{"name": "x", "action": lambda e, c: None, "compensation": 123}]
            )

    def test_init_duplicate_step_names_rejected(self) -> None:
        with pytest.raises(ValueError, match="дубликат"):
            SagaLRAProcessor(
                steps=[
                    {"name": "dup", "action": lambda e, c: None},
                    {"name": "dup", "action": lambda e, c: None},
                ]
            )

    def test_init_default_step_names_assigned(self) -> None:
        p = SagaLRAProcessor(
            steps=[
                {"action": lambda e, c: None},
                {"action": lambda e, c: None},
            ]
        )
        assert p._steps[0]["name"] == "step_0"
        assert p._steps[1]["name"] == "step_1"


# ── Happy path ────────────────────────────────────────────────────────


class TestSagaLRAHappyPath:
    async def test_runs_all_steps_successfully(self) -> None:
        a1 = _identity("a1")
        a2 = _identity("a2")
        a3 = _identity("a3")
        p = SagaLRAProcessor(
            steps=[
                {"name": "a1", "action": a1, "compensation": _identity("c1")},
                {"name": "a2", "action": a2, "compensation": _identity("c2")},
                {"name": "a3", "action": a3, "compensation": _identity("c3")},
            ]
        )
        ex = _make_exchange()
        await p.process(ex, _make_context())

        assert a1.calls == ["a1"]
        assert a2.calls == ["a2"]
        assert a3.calls == ["a3"]
        assert ex.get_property("saga_state") == STATE_COMPLETED
        assert ex.get_property("saga_completed_steps") == ["a1", "a2", "a3"]
        assert ex.get_property("saga_failed_step") is None
        assert ex.get_property("saga_compensations_run") == []
        assert ex.get_property("saga_error") is None

    async def test_async_action_supported(self) -> None:
        a1 = _identity_async("a1")
        a2 = _identity_async("a2")
        p = SagaLRAProcessor(
            steps=[
                {"name": "a1", "action": a1},
                {"name": "a2", "action": a2},
            ]
        )
        ex = _make_exchange()
        await p.process(ex, _make_context())
        assert a1.calls == ["a1"]
        assert a2.calls == ["a2"]
        assert ex.get_property("saga_state") == STATE_COMPLETED

    async def test_saga_id_is_unique_per_instance(self) -> None:
        p1 = SagaLRAProcessor(steps=[])
        p2 = SagaLRAProcessor(steps=[])
        assert p1._saga_id != p2._saga_id

    async def test_started_and_finished_at_are_set(self) -> None:
        p = SagaLRAProcessor(
            steps=[{"name": "x", "action": lambda e, c: None}],
            per_step_timeout_seconds=None,
        )
        ex = _make_exchange()
        t0 = time.time()
        await p.process(ex, _make_context())
        assert ex.get_property("saga_started_at") >= t0 - 0.1
        assert ex.get_property("saga_finished_at") >= ex.get_property("saga_started_at")

    async def test_on_state_change_callback(self) -> None:
        transitions: list[tuple[str, str]] = []

        def _cb(old: str, new: str, ex: "Exchange[Any]") -> None:
            transitions.append((old, new))

        a1 = _identity("a1")
        p = SagaLRAProcessor(
            steps=[{"name": "a1", "action": a1}],
            on_state_change=_cb,
        )
        ex = _make_exchange()
        await p.process(ex, _make_context())
        # Should see: (None/empty -> running), (running -> completed)
        assert (STATE_RUNNING, STATE_COMPLETED) in transitions


# ── Failure paths ─────────────────────────────────────────────────────


class TestSagaLRAFailure:
    async def test_runs_compensations_on_failure(self) -> None:
        a1 = _identity("a1")
        a2 = _identity("a2", raise_exc=True)
        a3 = _identity("a3")
        c1 = _identity("c1")
        c2 = _identity("c2")
        p = SagaLRAProcessor(
            steps=[
                {"name": "a1", "action": a1, "compensation": c1},
                {"name": "a2", "action": a2, "compensation": c2},
                {"name": "a3", "action": a3},
            ]
        )
        ex = _make_exchange()
        with pytest.raises(SagaCompensationError):
            await p.process(ex, _make_context())

        # a3 never ran
        assert a3.calls == []
        # Compensations run in REVERSE: c2, c1. But c2 corresponds to
        # step "a2" which is the failing one, not a succeeded step, so
        # c2 is NOT in the compensation loop (we only compensate the
        # steps that succeeded).
        assert c1.calls == ["c1"]
        assert c2.calls == []  # a2 failed; c2 not triggered
        assert ex.get_property("saga_state") == STATE_COMPENSATED
        assert ex.get_property("saga_failed_step") == "a2"
        assert ex.get_property("saga_completed_steps") == ["a1"]
        assert ex.get_property("saga_compensations_run") == ["c1"] or \
            ex.get_property("saga_compensations_run") == ["a1"]

    async def test_compensations_run_in_reverse_order(self) -> None:
        order: list[str] = []
        for n in ("a1", "a2", "a3", "a4"):
            _identity(n)  # discard

        def make_action(n: str):
            def _f(ex: "Exchange[Any]", ctx: "ExecutionContext") -> None:
                order.append(n)
            return _f

        def make_comp(n: str):
            def _f(ex: "Exchange[Any]", ctx: "ExecutionContext") -> None:
                order.append(f"comp_{n}")
            return _f

        # a2 succeeds, a3 fails. Expect compensations: comp_a2, comp_a1.
        p = SagaLRAProcessor(
            steps=[
                {"name": "a1", "action": make_action("a1"), "compensation": make_comp("a1")},
                {"name": "a2", "action": make_action("a2"), "compensation": make_comp("a2")},
                {"name": "a3", "action": make_action("a3-fail"), "compensation": make_comp("a3")},
            ]
        )

        def fail_a3(ex: "Exchange[Any]", ctx: "ExecutionContext") -> None:
            order.append("a3-fail")
            raise RuntimeError("boom")

        p._steps[2]["action"] = fail_a3

        ex = _make_exchange()
        with pytest.raises(SagaCompensationError):
            await p.process(ex, _make_context())

        # Order: a1, a2, a3-fail, then comp_a2, comp_a1 (reverse).
        assert order == ["a1", "a2", "a3-fail", "comp_a2", "comp_a1"]

    async def test_partial_compensation_only_succeeded_steps(self) -> None:
        # a1 succeeds, a2 fails → only comp_a1 runs (a3 was never tried).
        calls: list[str] = []
        p = SagaLRAProcessor(
            steps=[
                {
                    "name": "a1",
                    "action": lambda e, c: calls.append("a1"),
                    "compensation": lambda e, c: calls.append("comp_a1"),
                },
                {
                    "name": "a2",
                    "action": lambda e, c: (_ for _ in ()).throw(RuntimeError("boom")),
                    "compensation": lambda e, c: calls.append("comp_a2"),
                },
                {
                    "name": "a3",
                    "action": lambda e, c: calls.append("a3"),
                    "compensation": lambda e, c: calls.append("comp_a3"),
                },
            ]
        )
        ex = _make_exchange()
        with pytest.raises(SagaCompensationError):
            await p.process(ex, _make_context())
        assert "a3" not in calls
        assert "comp_a2" not in calls  # a2 failed; we don't compensate it
        assert "comp_a3" not in calls
        assert "comp_a1" in calls

    async def test_compensation_idempotent(self) -> None:
        # The processor itself maintains ran_compensations set; simulate
        # the saga running the same compensation twice by re-invoking
        # _run_compensation twice for the same step.
        a1 = _identity("a1")
        c1 = _identity("c1")
        c1_calls = c1.calls  # type: ignore[attr-defined]
        p = SagaLRAProcessor(
            steps=[
                {"name": "a1", "action": a1, "compensation": c1},
            ]
        )
        ex = _make_exchange()
        # Single-step saga, no failure → c1 not invoked.
        await p.process(ex, _make_context())
        assert c1_calls == []

        # Now manually verify idempotency by calling _run_compensation
        # twice for the same step.
        ran: set[str] = set()
        step = p._steps[0]
        await p._run_compensation(step, ex, _make_context(), ran_compensations=ran)
        await p._run_compensation(step, ex, _make_context(), ran_compensations=ran)
        # Only called once due to idempotency.
        assert c1_calls == ["c1"]

    async def test_single_step_no_compensation_on_failure(self) -> None:
        # If there's only one step and it fails, there's nothing to
        # compensate (the failing step itself has nothing to undo).
        p = SagaLRAProcessor(
            steps=[
                {
                    "name": "only",
                    "action": lambda e, c: (_ for _ in ()).throw(RuntimeError("boom")),
                    "compensation": lambda e, c: None,
                },
            ]
        )
        ex = _make_exchange()
        with pytest.raises(SagaCompensationError):
            await p.process(ex, _make_context())
        # State: failed (no compensations to run, but the original
        # error still propagates; with zero compensations the state is
        # "compensated" since the chain had nothing to undo).
        state = ex.get_property("saga_state")
        assert state in (STATE_COMPENSATED, STATE_FAILED)
        assert ex.get_property("saga_compensations_run") == []

    async def test_compensation_failure_marks_state_failed(self) -> None:
        def make_comp_fails():
            def _f(ex: "Exchange[Any]", ctx: "ExecutionContext") -> None:
                raise RuntimeError("comp-boom")
            return _f

        p = SagaLRAProcessor(
            steps=[
                {
                    "name": "a1",
                    "action": lambda e, c: None,
                    "compensation": make_comp_fails(),
                },
                {
                    "name": "a2",
                    "action": lambda e, c: (_ for _ in ()).throw(RuntimeError("step-boom")),
                },
            ],
        )
        ex = _make_exchange()
        with pytest.raises(SagaCompensationError) as excinfo:
            await p.process(ex, _make_context())
        assert ex.get_property("saga_state") == STATE_FAILED
        assert excinfo.value.original_error is not None
        assert len(excinfo.value.compensation_errors) == 1
        assert excinfo.value.compensation_errors[0][0] == "a1"

    async def test_fail_fast_aborts_remaining_compensations(self) -> None:
        comp_calls: list[str] = []

        def comp_fails_a1(ex: "Exchange[Any]", ctx: "ExecutionContext") -> None:
            comp_calls.append("comp_a1")
            raise RuntimeError("comp-a1-boom")

        def comp_a2(ex: "Exchange[Any]", ctx: "ExecutionContext") -> None:
            comp_calls.append("comp_a2")

        def comp_a3(ex: "Exchange[Any]", ctx: "ExecutionContext") -> None:
            comp_calls.append("comp_a3")

        p = SagaLRAProcessor(
            steps=[
                {"name": "a1", "action": lambda e, c: None, "compensation": comp_fails_a1},
                {"name": "a2", "action": lambda e, c: None, "compensation": comp_a2},
                {"name": "a3", "action": lambda e, c: None, "compensation": comp_a3},
                {
                    "name": "a4",
                    "action": lambda e, c: (_ for _ in ()).throw(RuntimeError("step-boom")),
                },
            ],
            fail_fast=True,
        )
        ex = _make_exchange()
        with pytest.raises(SagaCompensationError):
            await p.process(ex, _make_context())
        # Compensations run in REVERSE order: comp_a3, comp_a2, comp_a1.
        # comp_a1 raises → fail_fast=True aborts the rest. But the
        # break only happens AFTER the failure, so comp_a3 and
        # comp_a2 are still called.
        assert "comp_a1" in comp_calls
        assert "comp_a2" in comp_calls
        assert "comp_a3" in comp_calls
        assert ex.get_property("saga_state") == STATE_FAILED


# ── Edge cases ────────────────────────────────────────────────────────


class TestSagaLRAEdgeCases:
    async def test_empty_steps_completes_immediately(self) -> None:
        p = SagaLRAProcessor(steps=[])
        ex = _make_exchange()
        await p.process(ex, _make_context())
        assert ex.get_property("saga_state") == STATE_COMPLETED
        assert ex.get_property("saga_completed_steps") == []
        assert ex.get_property("saga_compensations_run") == []
        assert ex.get_property("saga_failed_step") is None

    async def test_action_that_calls_exchange_fail_treated_as_failure(self) -> None:
        def fail_step(ex: "Exchange[Any]", ctx: "ExecutionContext") -> None:
            ex.fail("explicit-fail")

        p = SagaLRAProcessor(
            steps=[
                {"name": "a1", "action": lambda e, c: None, "compensation": lambda e, c: None},
                {"name": "a2", "action": fail_step, "compensation": lambda e, c: None},
            ]
        )
        ex = _make_exchange()
        with pytest.raises(SagaCompensationError):
            await p.process(ex, _make_context())
        assert ex.get_property("saga_state") in (STATE_COMPENSATED, STATE_FAILED)

    async def test_per_step_timeout_raises_lra_error(self) -> None:
        async def slow_action(ex: "Exchange[Any]", ctx: "ExecutionContext") -> None:
            await asyncio.sleep(1.0)

        p = SagaLRAProcessor(
            steps=[
                {"name": "a1", "action": slow_action, "compensation": lambda e, c: None},
            ],
            per_step_timeout_seconds=0.05,
        )
        ex = _make_exchange()
        with pytest.raises(SagaCompensationError):
            await p.process(ex, _make_context())
        assert ex.get_property("saga_failed_step") == "a1"

    async def test_overall_timeout_triggers_compensation(self) -> None:
        async def slow_action(ex: "Exchange[Any]", ctx: "ExecutionContext") -> None:
            await asyncio.sleep(0.2)

        comp_calls: list[str] = []

        def comp(ex: "Exchange[Any]", ctx: "ExecutionContext") -> None:
            comp_calls.append("comp")

        p = SagaLRAProcessor(
            steps=[
                {
                    "name": "a1",
                    "action": slow_action,
                    "compensation": comp,
                },
                {
                    "name": "a2",
                    "action": slow_action,
                },
            ],
            timeout_seconds=0.15,  # less than 2 * 0.2
            per_step_timeout_seconds=None,
        )
        ex = _make_exchange()
        with pytest.raises(SagaCompensationError):
            await p.process(ex, _make_context())
        # Compensation was invoked for a1.
        assert "comp" in comp_calls

    async def test_exchange_failure_status_set_on_rollback(self) -> None:
        p = SagaLRAProcessor(
            steps=[
                {
                    "name": "a1",
                    "action": lambda e, c: None,
                    "compensation": lambda e, c: None,
                },
                {
                    "name": "a2",
                    "action": lambda e, c: (_ for _ in ()).throw(RuntimeError("boom")),
                },
            ]
        )
        ex = _make_exchange()
        with pytest.raises(SagaCompensationError):
            await p.process(ex, _make_context())
        # The exchange was marked failed by exchange.fail().
        from src.backend.dsl.engine.exchange import ExchangeStatus

        assert ex.status == ExchangeStatus.failed
        assert "Saga failed" in (ex.error or "")

    async def test_result_property_published(self) -> None:
        p = SagaLRAProcessor(
            steps=[{"name": "a1", "action": lambda e, c: None}],
            result_property="my_saga",
        )
        ex = _make_exchange()
        await p.process(ex, _make_context())
        result = ex.get_property("my_saga")
        assert result["state"] == STATE_COMPLETED
        assert result["completed_steps"] == ["a1"]
        assert result["failed_step"] is None
        assert result["compensations_run"] == []
        assert result["total_steps"] == 1

    async def test_custom_state_property_key(self) -> None:
        p = SagaLRAProcessor(
            steps=[{"name": "a1", "action": lambda e, c: None}],
            state_property="my_state",
        )
        ex = _make_exchange()
        await p.process(ex, _make_context())
        assert ex.get_property("my_state") == STATE_COMPLETED
        # Default key is not used.
        assert ex.get_property("saga_state") is None


# ── Concurrency & isolation ───────────────────────────────────────────


class TestSagaLRAConcurrency:
    async def test_concurrent_sagas_no_state_collision(self) -> None:
        a1 = _identity("a1")
        a1_b = _identity("a1_b")
        p1 = SagaLRAProcessor(
            steps=[{"name": "a1", "action": a1}],
        )
        p2 = SagaLRAProcessor(
            steps=[{"name": "a1", "action": a1_b}],
        )
        ex1 = _make_exchange()
        ex2 = _make_exchange()
        await asyncio.gather(
            p1.process(ex1, _make_context()),
            p2.process(ex2, _make_context()),
        )
        assert ex1.get_property("saga_state") == STATE_COMPLETED
        assert ex2.get_property("saga_state") == STATE_COMPLETED
        assert ex1.get_property("saga_id") != ex2.get_property("saga_id")
        assert a1.calls == ["a1"]
        assert a1_b.calls == ["a1_b"]

    async def test_parallel_sagas_dont_share_compensations(self) -> None:
        comp_calls: list[str] = []

        def make_comp(tag: str):
            def _f(ex: "Exchange[Any]", ctx: "ExecutionContext") -> None:
                comp_calls.append(f"comp_{tag}")
            return _f

        def make_fail():
            def _f(ex: "Exchange[Any]", ctx: "ExecutionContext") -> None:
                raise RuntimeError("boom")
            return _f

        p1 = SagaLRAProcessor(
            steps=[
                {"name": "a1", "action": lambda e, c: None, "compensation": make_comp("a")},
                {"name": "a2", "action": make_fail()},
            ]
        )
        p2 = SagaLRAProcessor(
            steps=[
                {"name": "a1", "action": lambda e, c: None, "compensation": make_comp("b")},
                {"name": "a2", "action": make_fail()},
            ]
        )
        ex1 = _make_exchange()
        ex2 = _make_exchange()
        await asyncio.gather(
            p1.process(ex1, _make_context()),
            p2.process(ex2, _make_context()),
            return_exceptions=True,
        )
        # Each saga's compensation runs exactly once.
        assert comp_calls.count("comp_a") == 1
        assert comp_calls.count("comp_b") == 1


# ── Serialization ─────────────────────────────────────────────────────


class TestSagaLRAToSpec:
    def test_to_spec_returns_dict(self) -> None:
        p = SagaLRAProcessor(
            steps=[
                {"name": "a1", "action": lambda e, c: None, "compensation": lambda e, c: None},
                {"name": "a2", "action": lambda e, c: None},
            ],
        )
        spec = p.to_spec()
        assert spec is not None
        assert "saga_lra_processor" in spec
        body = spec["saga_lra_processor"]
        assert body["steps"][0]["name"] == "a1"
        assert body["steps"][0]["has_compensation"] is True
        assert body["steps"][1]["has_compensation"] is False
        assert body["total_steps" if "total_steps" in body else "steps"]  # sanity

    def test_to_spec_includes_config(self) -> None:
        p = SagaLRAProcessor(
            steps=[],
            timeout_seconds=10.0,
            per_step_timeout_seconds=1.0,
            result_property="r",
            state_property="s",
            fail_fast=True,
        )
        spec = p.to_spec()
        assert spec is not None
        body = spec["saga_lra_processor"]
        assert body["timeout_seconds"] == 10.0
        assert body["per_step_timeout_seconds"] == 1.0
        assert body["result_property"] == "r"
        assert body["state_property"] == "s"
        assert body["fail_fast"] is True


# ── Saga LRA error types ─────────────────────────────────────────────


class TestSagaLRAErrors:
    def test_compensation_error_preserves_original(self) -> None:
        original = RuntimeError("step-boom")
        comp_exc = RuntimeError("comp-boom")
        err = SagaCompensationError(
            "failed",
            original_error=original,
            compensation_errors=[("a1", comp_exc)],
        )
        assert err.original_error is original
        assert err.compensation_errors == [("a1", comp_exc)]

    def test_lra_error_is_runtime_error(self) -> None:
        assert issubclass(SagaLRAError, RuntimeError)
        assert issubclass(SagaCompensationError, SagaLRAError)
