"""Unit tests для Airflow-style operators (Sprint 56 W2).

Coverage:
* BranchPythonOperator — 4 tests (sync, async, allowed_branches validation, error capture)
* ShortCircuitOperator — 3 tests (True, False, ignore_trigger_rules)
* LatestOnlyOperator — 3 tests (latest, not latest, custom checker)
* BranchDateTimeOperator — 3 tests (in window, out of window, lower>upper validation)
* ExternalTaskSensor — 5 tests (success state, polling, timeout, failed state, custom check_fn)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.orchestration.airflow_operators import (
    BRANCH_DECISION_PROPERTY,
    BRANCH_SKIP_VALUE,
    BranchDateTimeOperator,
    BranchPythonOperator,
    BranchSelector,
    ExternalTaskSensor,
    LatestOnlyOperator,
    ShortCircuitOperator,
)


def _exchange(body: object = "", headers: dict | None = None) -> Exchange:
    msg = Message(body=body, headers=headers or {})
    return Exchange(in_message=msg)


def _ctx() -> ExecutionContext:
    return ExecutionContext()


# ── BranchPythonOperator ─────────────────────────────────────────────


class TestBranchPython:
    @pytest.mark.asyncio
    async def test_sync_callable(self) -> None:
        """Sync callable returns branch name."""
        op = BranchPythonOperator(
            python_callable=lambda ex: "high" if ex.in_message.body > 100 else "low"
        )
        ex = _exchange(150)
        await op.process(ex, _ctx())
        assert ex.get_property(BRANCH_DECISION_PROPERTY) == "high"

        ex2 = _exchange(50)
        await op.process(ex2, _ctx())
        assert ex2.get_property(BRANCH_DECISION_PROPERTY) == "low"

    @pytest.mark.asyncio
    async def test_async_callable(self) -> None:
        """Async callable (coroutine function) awaited correctly."""

        async def pick(ex: Exchange) -> str:
            await asyncio.sleep(0)
            return "async_branch"

        op = BranchPythonOperator(python_callable=pick)
        ex = _exchange({})
        await op.process(ex, _ctx())
        assert ex.get_property(BRANCH_DECISION_PROPERTY) == "async_branch"

    @pytest.mark.asyncio
    async def test_allowed_branches_validation(self) -> None:
        """Callable returns non-whitelisted branch → error captured."""
        op = BranchPythonOperator(
            python_callable=lambda ex: "rogue", allowed_branches=["good1", "good2"]
        )
        ex = _exchange({})
        await op.process(ex, _ctx())
        assert ex.error is not None
        assert "rogue" in ex.error
        assert "allowed_branches" in ex.error

    @pytest.mark.asyncio
    async def test_skip_value(self) -> None:
        """Callable returns BRANCH_SKIP_VALUE → skip sentinel set."""
        op = BranchPythonOperator(python_callable=lambda ex: BRANCH_SKIP_VALUE)
        ex = _exchange({})
        await op.process(ex, _ctx())
        assert ex.get_property(BRANCH_DECISION_PROPERTY) == BRANCH_SKIP_VALUE


# ── ShortCircuitOperator ────────────────────────────────────────────


class TestShortCircuit:
    @pytest.mark.asyncio
    async def test_predicate_true_continues(self) -> None:
        """Predicate=True → no decision set, exchange NOT stopped."""
        op = ShortCircuitOperator(predicate=lambda ex: ex.in_message.body["ok"])
        ex = _exchange({"ok": True})
        await op.process(ex, _ctx())
        assert ex.get_property(BRANCH_DECISION_PROPERTY) is None
        assert ex.error is None

    @pytest.mark.asyncio
    async def test_predicate_false_skips(self) -> None:
        """Predicate=False → BRANCH_SKIP_VALUE + exchange stopped."""
        op = ShortCircuitOperator(
            predicate=lambda ex: ex.in_message.body.get("ok", False)
        )
        ex = _exchange({"ok": False})
        await op.process(ex, _ctx())
        assert ex.get_property(BRANCH_DECISION_PROPERTY) == BRANCH_SKIP_VALUE
        # handle_processor_error: error stored only if exception; stop() doesn't set error
        assert ex.error is None

    @pytest.mark.asyncio
    async def test_ignore_trigger_rules(self) -> None:
        """ignore_downstream_trigger_rules=True → force_skip property set."""
        op = ShortCircuitOperator(
            predicate=lambda ex: False, ignore_downstream_trigger_rules=True
        )
        ex = _exchange({})
        await op.process(ex, _ctx())
        assert ex.get_property("short_circuit.force_skip") is True
        assert ex.get_property(BRANCH_DECISION_PROPERTY) == BRANCH_SKIP_VALUE


# ── LatestOnlyOperator ──────────────────────────────────────────────


class TestLatestOnly:
    @pytest.mark.asyncio
    async def test_latest_run_continues(self) -> None:
        """is_latest_run=True header → no skip."""
        op = LatestOnlyOperator()
        ex = _exchange({}, headers={"is_latest_run": True})
        await op.process(ex, _ctx())
        assert ex.get_property(BRANCH_DECISION_PROPERTY) is None

    @pytest.mark.asyncio
    async def test_old_run_skipped(self) -> None:
        """is_latest_run=False → skip + latest_only.skipped set."""
        op = LatestOnlyOperator()
        ex = _exchange({}, headers={"is_latest_run": False})
        await op.process(ex, _ctx())
        assert ex.get_property(BRANCH_DECISION_PROPERTY) == BRANCH_SKIP_VALUE
        assert ex.get_property("latest_only.skipped") is True

    @pytest.mark.asyncio
    async def test_custom_checker(self) -> None:
        """Custom latest_run_checker callable (not header-based)."""

        def checker(ex: Exchange) -> bool:
            return ex.in_message.body["run_id"] == "latest"

        op = LatestOnlyOperator(latest_run_checker=checker)
        ex_latest = _exchange({"run_id": "latest"})
        await op.process(ex_latest, _ctx())
        assert ex_latest.get_property(BRANCH_DECISION_PROPERTY) is None

        ex_old = _exchange({"run_id": "backfill-2024-01-01"})
        await op.process(ex_old, _ctx())
        assert ex_old.get_property(BRANCH_DECISION_PROPERTY) == BRANCH_SKIP_VALUE


# ── BranchDateTimeOperator ──────────────────────────────────────────


class TestBranchDateTime:
    @pytest.mark.asyncio
    async def test_in_window(self) -> None:
        """Текущее время в окне → true_branch."""
        now = datetime.utcnow()
        op = BranchDateTimeOperator(
            target_task_if_true="weekday_job",
            target_task_if_false="weekend_job",
            target_lower=now - timedelta(hours=1),
            target_upper=now + timedelta(hours=1),
        )
        ex = _exchange({})
        await op.process(ex, _ctx())
        assert ex.get_property(BRANCH_DECISION_PROPERTY) == "weekday_job"

    @pytest.mark.asyncio
    async def test_out_of_window(self) -> None:
        """Текущее время вне окна → false_branch."""
        op = BranchDateTimeOperator(
            target_task_if_true="future_job",
            target_task_if_false="current_job",
            target_lower=datetime(2030, 1, 1),
            target_upper=datetime(2030, 12, 31),
        )
        ex = _exchange({})
        await op.process(ex, _ctx())
        assert ex.get_property(BRANCH_DECISION_PROPERTY) == "current_job"

    @pytest.mark.asyncio
    async def test_uses_execution_date(self) -> None:
        """use_task_execution_date=True + execution_date header используется."""
        target = datetime(2025, 6, 1, 12, 0, 0)
        op = BranchDateTimeOperator(
            target_task_if_true="old_job",
            target_task_if_false="new_job",
            target_lower=datetime(2025, 1, 1),
            target_upper=datetime(2025, 12, 31),
        )
        ex = _exchange({}, headers={"execution_date": target})
        await op.process(ex, _ctx())
        assert ex.get_property(BRANCH_DECISION_PROPERTY) == "old_job"

    def test_lower_greater_than_upper_raises(self) -> None:
        """lower > upper → ValueError at construction."""
        with pytest.raises(ValueError, match="target_lower > target_upper"):
            BranchDateTimeOperator(
                target_task_if_true="a",
                target_task_if_false="b",
                target_lower=datetime(2030, 6, 1),
                target_upper=datetime(2020, 1, 1),
            )


# ── ExternalTaskSensor ──────────────────────────────────────────────


class TestExternalTaskSensor:
    @pytest.mark.asyncio
    async def test_immediate_success(self) -> None:
        """getter сразу возвращает 'success' → no polling, exchange property set."""

        def getter(_dag: str, _task: str | None, _exec: object) -> str:
            return "success"

        op = ExternalTaskSensor(
            external_dag_id="upstream_dag", task_state_getter=getter
        )
        ex = _exchange({})
        await op.process(ex, _ctx())
        assert ex.get_property("external_task_sensor.last_state") == "success"
        assert op.stats()["matches"] == 1
        assert op.stats()["polls"] == 1

    @pytest.mark.asyncio
    async def test_polling_until_success(self) -> None:
        """getter возвращает 'running' 2 раза, потом 'success'."""
        states = ["running", "running", "success"]
        idx = {"i": 0}

        def getter(_dag: str, _task: str | None, _exec: object) -> str:
            s = states[idx["i"]]
            idx["i"] += 1
            return s

        op = ExternalTaskSensor(
            external_dag_id="d", task_state_getter=getter, poll_interval_s=0.01
        )
        ex = _exchange({})
        await op.process(ex, _ctx())
        assert ex.get_property("external_task_sensor.last_state") == "success"
        assert op.stats()["polls"] == 3
        assert op.stats()["matches"] == 1

    @pytest.mark.asyncio
    async def test_failed_state_raises(self) -> None:
        """getter возвращает 'failed' → RuntimeError (per failed_states)."""

        def getter(_dag: str, _task: str | None, _exec: object) -> str:
            return "failed"

        op = ExternalTaskSensor(external_dag_id="d", task_state_getter=getter)
        ex = _exchange({})
        await op.process(ex, _ctx())
        assert ex.error is not None
        assert "failed state" in ex.error

    @pytest.mark.asyncio
    async def test_timeout(self) -> None:
        """getter всегда 'running' → timeout after timeout_s."""

        def getter(_dag: str, _task: str | None, _exec: object) -> str:
            return "running"

        op = ExternalTaskSensor(
            external_dag_id="d",
            task_state_getter=getter,
            poll_interval_s=0.01,
            timeout_s=0.05,
        )
        ex = _exchange({})
        await op.process(ex, _ctx())
        assert ex.error is not None
        assert "timeout" in ex.error.lower()
        assert op.stats()["timeouts"] == 1

    @pytest.mark.asyncio
    async def test_custom_check_fn(self) -> None:
        """check_fn передан → используется вместо allowed_states check."""
        states = ["queued", "running", "done"]
        idx = {"i": 0}

        def getter(_dag: str, _task: str | None, _exec: object) -> str:
            s = states[idx["i"]]
            idx["i"] += 1
            return s

        def my_check(_ex: Exchange, state: str) -> bool:
            return state == "done"

        op = ExternalTaskSensor(
            external_dag_id="d",
            task_state_getter=getter,
            check_fn=my_check,
            poll_interval_s=0.01,
        )
        ex = _exchange({})
        await op.process(ex, _ctx())
        assert ex.get_property("external_task_sensor.last_state") == "done"
        assert op.stats()["matches"] == 1


# ── BranchSelector ──────────────────────────────────────────────────


class TestBranchSelector:
    def test_resolve_returns_decision(self) -> None:
        sel = BranchSelector()
        ex = _exchange({})
        ex.set_property(BRANCH_DECISION_PROPERTY, "branch_x")
        assert sel.resolve(ex) == "branch_x"

    def test_resolve_no_decision(self) -> None:
        sel = BranchSelector()
        ex = _exchange({})
        assert sel.resolve(ex) is None

    def test_is_skip_true(self) -> None:
        sel = BranchSelector()
        ex = _exchange({})
        ex.set_property(BRANCH_DECISION_PROPERTY, BRANCH_SKIP_VALUE)
        assert sel.is_skip(ex) is True

    def test_is_skip_false_for_normal_branch(self) -> None:
        sel = BranchSelector()
        ex = _exchange({})
        ex.set_property(BRANCH_DECISION_PROPERTY, "branch_x")
        assert sel.is_skip(ex) is False
