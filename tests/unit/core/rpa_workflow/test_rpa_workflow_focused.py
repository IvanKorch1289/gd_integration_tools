"""Focused tests for ``core.rpa_workflow`` (Wave 3 RPA)."""

from __future__ import annotations

import asyncio

import pytest

from src.backend.core.rpa_workflow import (
    Checkpoint,
    RPAState,
    RPAWorkflow,
    Selector,
    SelectorChain,
    SelectorStrategy,
    SelectorType,
    WorkflowRun,
    get_rpa_workflow,
)
from src.backend.core.rpa_workflow.workflow import reset_rpa_workflow


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_rpa_workflow()


class TestSelectorType:
    def test_values(self) -> None:
        assert SelectorType.CSS.value == "css"
        assert SelectorType.XPATH.value == "xpath"
        assert SelectorType.ARIA.value == "aria"
        assert SelectorType.DATA_TESTID.value == "data-testid"


class TestSelectorStrategy:
    def test_values(self) -> None:
        assert SelectorStrategy.FIRST.value == "first"
        assert SelectorStrategy.FALLBACK.value == "fallback"
        assert SelectorStrategy.ALL.value == "all"


class TestSelector:
    def test_init(self) -> None:
        s = Selector(selector_type=SelectorType.CSS, value="button.x")
        assert s.description == ""


class TestSelectorChain:
    def test_init(self) -> None:
        chain = SelectorChain()
        assert chain.selectors == []
        assert chain.strategy == SelectorStrategy.FALLBACK

    def test_init_with_selectors(self) -> None:
        chain = SelectorChain(
            selectors=[
                Selector(SelectorType.CSS, "button.x"),
                Selector(SelectorType.ARIA, "Submit"),
            ],
            strategy=SelectorStrategy.FALLBACK,
        )
        assert len(chain.selectors) == 2

    def test_resolve_first(self) -> None:
        chain = SelectorChain(
            selectors=[
                Selector(SelectorType.CSS, "css-1"),
                Selector(SelectorType.ARIA, "aria-1"),
            ],
            strategy=SelectorStrategy.FIRST,
        )
        s = chain.resolve(attempt=0)
        assert s.value == "css-1"
        # First strategy → always returns first.
        s2 = chain.resolve(attempt=1)
        assert s2.value == "css-1"

    def test_resolve_fallback(self) -> None:
        chain = SelectorChain(
            selectors=[
                Selector(SelectorType.CSS, "css-1"),
                Selector(SelectorType.ARIA, "aria-1"),
                Selector(SelectorType.DATA_TESTID, "test-1"),
            ],
            strategy=SelectorStrategy.FALLBACK,
        )
        assert chain.resolve(0).value == "css-1"
        assert chain.resolve(1).value == "aria-1"
        assert chain.resolve(2).value == "test-1"
        # Past end → None.
        assert chain.resolve(3) is None

    def test_resolve_empty(self) -> None:
        chain = SelectorChain()
        assert chain.resolve() is None

    def test_attempts_count(self) -> None:
        chain_first = SelectorChain(strategy=SelectorStrategy.FIRST)
        assert chain_first.attempts_count() == 1
        chain_fallback = SelectorChain(
            selectors=[
                Selector(SelectorType.CSS, "a"),
                Selector(SelectorType.ARIA, "b"),
            ],
            strategy=SelectorStrategy.FALLBACK,
        )
        assert chain_fallback.attempts_count() == 2


class TestRPAStateEnum:
    def test_values(self) -> None:
        assert RPAState.PENDING.value == "pending"
        assert RPAState.RUNNING.value == "running"
        assert RPAState.PAUSED.value == "paused"
        assert RPAState.COMPLETED.value == "completed"
        assert RPAState.FAILED.value == "failed"


class TestCheckpoint:
    def test_defaults(self) -> None:
        cp = Checkpoint(step_name="s1", state=RPAState.RUNNING)
        assert cp.timestamp == 0.0
        assert cp.data == {}
        assert cp.screenshot_path is None

    def test_with_all(self) -> None:
        cp = Checkpoint(
            step_name="s1",
            state=RPAState.PAUSED,
            timestamp=123.0,
            data={"k": "v"},
            screenshot_path="/tmp/sc.png",
        )
        assert cp.timestamp == 123.0
        assert cp.screenshot_path == "/tmp/sc.png"


class TestWorkflowRun:
    def test_defaults(self) -> None:
        r = WorkflowRun(run_id="r1", workflow_id="w1")
        assert r.state == RPAState.PENDING
        assert r.started_at == 0.0
        assert r.paused_at is None
        assert r.completed_at is None
        assert r.checkpoints == []
        assert r.last_error is None
        assert r.pause_reason is None
        assert r.operator is None


class TestRPAWorkflowInit:
    def test_init(self) -> None:
        wf = RPAWorkflow()
        assert wf.list_all() == []


class TestWorkflowStart:
    async def test_start_creates_run(self) -> None:
        wf = RPAWorkflow()
        run = await wf.start(workflow_id="payment-flow")
        assert run.run_id  # UUID
        assert run.workflow_id == "payment-flow"
        assert run.state == RPAState.RUNNING
        assert len(wf.list_all()) == 1

    async def test_start_with_metadata(self) -> None:
        wf = RPAWorkflow()
        run = await wf.start(
            workflow_id="w1", metadata={"initiator": "alice"}
        )
        assert run.metadata == {"initiator": "alice"}


class TestWorkflowRunStep:
    async def test_run_step_creates_checkpoint(self) -> None:
        wf = RPAWorkflow()
        run = await wf.start(workflow_id="w1")
        cp = await wf.run_step(run, step_name="navigate", screenshot_path="/tmp/sc.png")
        assert cp.step_name == "navigate"
        assert cp.screenshot_path == "/tmp/sc.png"
        assert len(run.checkpoints) == 1

    async def test_run_step_multiple(self) -> None:
        wf = RPAWorkflow()
        run = await wf.start(workflow_id="w1")
        await wf.run_step(run, step_name="step1")
        await wf.run_step(run, step_name="step2")
        await wf.run_step(run, step_name="step3")
        assert len(run.checkpoints) == 3

    async def test_run_step_in_paused_state(self) -> None:
        """Step can run while paused (e.g., diagnostics)."""
        wf = RPAWorkflow()
        run = await wf.start(workflow_id="w1")
        await wf.pause(run, reason="MFA required")
        cp = await wf.run_step(run, step_name="diagnostic")
        assert cp.step_name == "diagnostic"

    async def test_run_step_in_completed_raises(self) -> None:
        wf = RPAWorkflow()
        run = await wf.start(workflow_id="w1")
        await wf.complete(run)
        with pytest.raises(RuntimeError, match="Cannot run step"):
            await wf.run_step(run, step_name="after_complete")

    async def test_run_step_in_failed_raises(self) -> None:
        wf = RPAWorkflow()
        run = await wf.start(workflow_id="w1")
        await wf.fail(run, error="boom")
        with pytest.raises(RuntimeError):
            await wf.run_step(run, step_name="after_fail")


class TestWorkflowPause:
    async def test_pause(self) -> None:
        wf = RPAWorkflow()
        run = await wf.start(workflow_id="w1")
        await wf.pause(run, reason="CAPTCHA required")
        assert run.state == RPAState.PAUSED
        assert run.pause_reason == "CAPTCHA required"
        assert run.paused_at is not None

    async def test_pause_with_operator(self) -> None:
        wf = RPAWorkflow()
        run = await wf.start(workflow_id="w1")
        await wf.pause(run, reason="MFA", operator="alice")
        assert run.operator == "alice"

    async def test_pause_already_paused_raises(self) -> None:
        wf = RPAWorkflow()
        run = await wf.start(workflow_id="w1")
        await wf.pause(run, reason="x")
        with pytest.raises(RuntimeError, match="Cannot pause"):
            await wf.pause(run, reason="y")

    async def test_pause_completed_raises(self) -> None:
        wf = RPAWorkflow()
        run = await wf.start(workflow_id="w1")
        await wf.complete(run)
        with pytest.raises(RuntimeError):
            await wf.pause(run, reason="x")


class TestWorkflowResume:
    async def test_resume(self) -> None:
        wf = RPAWorkflow()
        run = await wf.start(workflow_id="w1")
        await wf.pause(run, reason="MFA")
        await wf.resume(run)
        assert run.state == RPAState.RUNNING
        assert run.resumed_at is not None

    async def test_resume_with_operator(self) -> None:
        wf = RPAWorkflow()
        run = await wf.start(workflow_id="w1")
        await wf.pause(run, reason="x", operator="alice")
        await wf.resume(run, operator="bob")
        assert run.operator == "bob"

    async def test_resume_not_paused_raises(self) -> None:
        wf = RPAWorkflow()
        run = await wf.start(workflow_id="w1")
        with pytest.raises(RuntimeError):
            await wf.resume(run)


class TestWorkflowComplete:
    async def test_complete(self) -> None:
        wf = RPAWorkflow()
        run = await wf.start(workflow_id="w1")
        await wf.complete(run)
        assert run.state == RPAState.COMPLETED
        assert run.completed_at is not None


class TestWorkflowFail:
    async def test_fail(self) -> None:
        wf = RPAWorkflow()
        run = await wf.start(workflow_id="w1")
        await wf.fail(run, error="selector not found")
        assert run.state == RPAState.FAILED
        assert run.last_error == "selector not found"


class TestWorkflowGet:
    async def test_get(self) -> None:
        wf = RPAWorkflow()
        run = await wf.start(workflow_id="w1")
        assert wf.get(run.run_id) is run

    async def test_get_missing(self) -> None:
        wf = RPAWorkflow()
        assert wf.get("missing") is None


class TestWorkflowList:
    async def test_list_by_workflow(self) -> None:
        wf = RPAWorkflow()
        await wf.start(workflow_id="w1")
        await wf.start(workflow_id="w2")
        await wf.start(workflow_id="w1")
        runs = wf.list_by_workflow("w1")
        assert len(runs) == 2

    async def test_list_by_state(self) -> None:
        wf = RPAWorkflow()
        r1 = await wf.start(workflow_id="w1")
        await wf.start(workflow_id="w2")
        await wf.complete(r1)
        completed = wf.list_by_state(RPAState.COMPLETED)
        running = wf.list_by_state(RPAState.RUNNING)
        assert len(completed) == 1
        assert len(running) == 1


class TestSingleton:
    def test_singleton(self) -> None:
        w1 = get_rpa_workflow()
        w2 = get_rpa_workflow()
        assert w1 is w2

    def test_reset(self) -> None:
        w1 = get_rpa_workflow()
        reset_rpa_workflow()
        w2 = get_rpa_workflow()
        assert w1 is not w2


class TestExports:
    def test_module_all(self) -> None:
        from src.backend.core import rpa_workflow

        assert len(rpa_workflow.__all__) == 9


class TestRealisticExample:
    async def test_full_payment_workflow(self) -> None:
        """Realistic: payment flow with HITL for MFA."""
        wf = get_rpa_workflow()
        run = await wf.start(
            workflow_id="payment-flow",
            metadata={"amount": 100, "currency": "USD"},
        )
        # Step 1: navigate to payment page.
        await wf.run_step(run, "navigate_to_payment")
        # Step 2: fill form.
        await wf.run_step(run, "fill_card_form")
        # Step 3: MFA → pause for operator.
        await wf.pause(run, reason="MFA required", operator="alice")
        # ... operator completes MFA ...
        await wf.resume(run, operator="alice")
        # Step 4: submit.
        await wf.run_step(run, "submit_payment")
        # Complete.
        await wf.complete(run)
        assert run.state == RPAState.COMPLETED
        assert len(run.checkpoints) == 3
        assert run.pause_reason == "MFA required"
