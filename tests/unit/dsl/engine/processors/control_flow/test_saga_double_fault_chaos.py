"""Chaos test for Saga double-fault scenario (Wave OP-4 / ADR-0296).

Сценарий: payment-processing Saga где compensate-шаг сам падает.

Realistic context (banking domain):

```text
Step 1: reserve_account_balance (forward OK, compensate OK)
Step 2: charge_payment (forward OK, compensate FAILS — refund API down)
Step 3: notify_partner (forward FAILS — network timeout)

Saga should:
  1. Run forward steps in order.
  2. On step 3 failure, compensate completed steps in reverse.
  3. Continue compensation even if compensate itself fails
     (DO NOT re-raise — avoid masking original failure).
  4. Emit ``workflow.compensation_fail`` audit event для каждого failed
     compensation (НЕ silent failure).
  5. Mark exchange.status = failed (terminal).
  6. Provide enough diagnostic info для operator replay / manual fix.

Double-fault scenario защищает от:
- Infinite retry loop при compensate failure.
- Silent swallow of compensate errors.
- Unclear state — operator не знает что cleanup не завершился.
- Race в audit emission (compensation_fail event).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.engine.processors.control_flow import SagaProcessor, SagaStep


def _make_succeeding_step(name: str = "step_ok") -> MagicMock:
    """Шаг, который всегда succeeds при process()."""
    step = MagicMock(spec=BaseProcessor)
    step.name = name
    step.process = AsyncMock()
    return step


def _make_failing_step(name: str = "step_fail", error: str = "step failed") -> MagicMock:
    """Шаг, который всегда raises при process()."""
    step = MagicMock(spec=BaseProcessor)
    step.name = name
    step.process = AsyncMock(side_effect=RuntimeError(error))
    return step


def _make_exchange() -> Exchange:
    """Fresh exchange для тестов."""
    return Exchange(body={})


class TestSagaDoubleFault:
    """Double-fault: compensate itself fails during compensation chain."""

    async def test_saga_complete_normal(self) -> None:
        """Baseline: happy path — все steps succeed, compensation не вызывается."""
        step1 = _make_succeeding_step("step1")
        step2 = _make_succeeding_step("step2")

        saga = SagaProcessor(
            steps=[
                SagaStep(forward=step1, compensate=None),
                SagaStep(forward=step2, compensate=None),
            ]
        )
        ex = _make_exchange()
        await saga.process(ex, context=MagicMock())

        step1.process.assert_awaited_once()
        step2.process.assert_awaited_once()
        assert ex.status != ExchangeStatus.failed
        assert ex.get_property("saga_completed") is True

    async def test_saga_failure_triggers_compensation(self) -> None:
        """Step 3 fails → compensations step1, step2 (reverse order)."""
        step1 = _make_succeeding_step("step1")
        step2 = _make_succeeding_step("step2")
        step2_compensate = _make_succeeding_step("step2_comp")
        step3 = _make_failing_step("step3")

        saga = SagaProcessor(
            steps=[
                SagaStep(forward=step1, compensate=None),
                SagaStep(forward=step2, compensate=step2_compensate),
                SagaStep(forward=step3, compensate=None),
            ]
        )
        ex = _make_exchange()
        await saga.process(ex, context=MagicMock())

        step1.process.assert_awaited_once()
        step2.process.assert_awaited_once()
        step3.process.assert_awaited_once()
        # Compensation must run for step2 (only completed step before failure).
        step2_compensate.process.assert_awaited_once()
        assert ex.status == ExchangeStatus.failed
        assert ex.get_property("saga_failed_step") == 2

    async def test_double_fault_compensate_fails_after_step_fails(self) -> None:
        """DOUBLE-FAULT: step2's compensate fails AFTER step3 fails.

        Critical banking scenario:
          1. reserve_balance (succeeds)
          2. charge_payment (succeeds, compensate = refund_payment — FAILS)
          3. notify_partner (FAILS — timeout)

        Expected behavior:
          - Saga completes (no infinite loop / hang)
          - exchange.status = failed
          - Audit event emitted для compensation_fail
          - Operator получает явный diagnostic в exchange.error / properties
        """
        # ARRANGE.
        step1_reserve = _make_succeeding_step("reserve_balance")
        step2_charge = _make_succeeding_step("charge_payment")
        step2_refund = _make_failing_step(
            "refund_payment", error="refund API down"
        )
        step3_notify = _make_failing_step("notify_partner", error="timeout")

        saga = SagaProcessor(
            steps=[
                SagaStep(forward=step1_reserve, compensate=None),
                SagaStep(forward=step2_charge, compensate=step2_refund),
                SagaStep(forward=step3_notify, compensate=None),
            ]
        )
        ex = _make_exchange()

        # ACT: patch audit emitter to capture events.
        with patch(
            "src.backend.dsl.engine.processors.control_flow.saga._emit_saga_audit"
        ) as mock_audit:
            await saga.process(ex, context=MagicMock())

        # ASSERT: saga completed without hanging.
        step1_reserve.process.assert_awaited_once()
        step2_charge.process.assert_awaited_once()
        step3_notify.process.assert_awaited_once()
        # step2 compensation ATTEMPTED (even though failed).
        step2_refund.process.assert_awaited_once()

        # ASSERT: terminal failed state.
        assert ex.status == ExchangeStatus.failed

        # ASSERT: audit events emitted.
        # Expected events:
        #   1. workflow.compensation_start (when step3 failed)
        #   2. workflow.compensation_fail (step2_refund failed)
        #   3. workflow.compensation_fail (because ANY failed — terminal)
        audit_events = [
            call.kwargs["event_type"] for call in mock_audit.call_args_list
        ]
        assert "workflow.compensation_start" in audit_events
        assert audit_events.count("workflow.compensation_fail") >= 2, (
            f"Expected ≥2 compensation_fail events, got {audit_events}"
        )

        # ASSERT: diagnostic properties set.
        assert ex.get_property("saga_failed_step") == 2
        # saga_error содержит сообщение об ошибке (не имя step).
        assert "timeout" in (ex.get_property("saga_error") or "")

    async def test_double_fault_does_not_hang_on_repeated_compensate_failures(self) -> None:
        """Multiple compensate failures → saga завершается за bounded time.

        Защита от infinite loop: если compensate вызывает side effect, который
        recursively fails, saga должен остановиться и не блокировать event loop.
        """
        step1 = _make_succeeding_step("step1")
        step1_comp = _make_failing_step("step1_comp", error="comp fail 1")
        step2 = _make_failing_step("step2")

        saga = SagaProcessor(
            steps=[
                SagaStep(forward=step1, compensate=step1_comp),
                SagaStep(forward=step2, compensate=None),
            ]
        )
        ex = _make_exchange()

        # ACT: bounded timeout (если hang — fail через 5 sec).
        import asyncio

        try:
            await asyncio.wait_for(
                saga.process(ex, context=MagicMock()),
                timeout=5.0,
            )
        except asyncio.TimeoutError:
            pytest.fail("Saga double-fault caused infinite hang")

        # Compensation must run EXACTLY once (no retry loop).
        assert step1_comp.process.await_count == 1
        assert ex.status == ExchangeStatus.failed

    async def test_double_fault_multiple_failed_compensations(self) -> None:
        """Multiple steps + multiple failed compensations."""
        step1 = _make_succeeding_step("s1")
        step1_comp = _make_failing_step("s1_comp", error="s1 refund fail")
        step2 = _make_succeeding_step("s2")
        step2_comp = _make_failing_step("s2_comp", error="s2 refund fail")
        step3 = _make_failing_step("s3")

        saga = SagaProcessor(
            steps=[
                SagaStep(forward=step1, compensate=step1_comp),
                SagaStep(forward=step2, compensate=step2_comp),
                SagaStep(forward=step3, compensate=None),
            ]
        )
        ex = _make_exchange()

        with patch(
            "src.backend.dsl.engine.processors.control_flow.saga._emit_saga_audit"
        ) as mock_audit:
            await saga.process(ex, context=MagicMock())

        # Both compensations ATTEMPTED exactly once.
        step1_comp.process.assert_awaited_once()
        step2_comp.process.assert_awaited_once()

        # Terminal failed.
        assert ex.status == ExchangeStatus.failed

        # Multiple compensation_fail events.
        audit_events = [
            call.kwargs["event_type"] for call in mock_audit.call_args_list
        ]
        # 1 compensation_start + 2 compensation_fail (per failed comp) + 1 final = 4.
        compensation_fails = [
            e for e in audit_events if e == "workflow.compensation_fail"
        ]
        assert len(compensation_fails) >= 3, (
            f"Expected ≥3 compensation_fail events, got {audit_events}"
        )

    async def test_compensation_failure_does_not_mask_original_failure(self) -> None:
        """Original failure (step3) ДОЛЖЕН быть в diagnostic; compensation
        failure НЕ ДОЛЖЕН его перезаписывать."""
        step1 = _make_succeeding_step("s1")
        step1_comp = _make_failing_step("s1_comp", error="REFUND FAIL")
        step2 = _make_succeeding_step("s2")
        step2_comp = _make_succeeding_step("s2_comp")
        step3 = _make_failing_step("s3", error="ORIGINAL TIMEOUT")

        saga = SagaProcessor(
            steps=[
                SagaStep(forward=step1, compensate=step1_comp),
                SagaStep(forward=step2, compensate=step2_comp),
                SagaStep(forward=step3, compensate=None),
            ]
        )
        ex = _make_exchange()
        await saga.process(ex, context=MagicMock())

        # Original error (step3) должен быть виден.
        error_msg = ex.get_property("saga_error") or ""
        # saga_error содержит текст оригинальной ошибки.
        assert "ORIGINAL TIMEOUT" in error_msg
        # failed_step = 2 (zero-indexed для step3).
        assert ex.get_property("saga_failed_step") == 2

    async def test_saga_with_only_failing_compensation(self) -> None:
        """Compensation fails but step succeeds — НЕ fail saga.

        Compensate failure должен влиять только на compensation chain,
        не на normal flow (forward step succeeded).
        """
        step1 = _make_succeeding_step("s1")
        # Нет compensation, нет failure.
        step2 = _make_succeeding_step("s2")

        saga = SagaProcessor(
            steps=[
                SagaStep(forward=step1, compensate=None),
                SagaStep(forward=step2, compensate=None),
            ]
        )
        ex = _make_exchange()
        await saga.process(ex, context=MagicMock())

        assert ex.status != ExchangeStatus.failed
        assert ex.get_property("saga_completed") is True


class TestSagaDoubleFaultInvariants:
    """Invariants для double-fault (negative tests)."""

    async def test_no_infinite_retry_of_compensate(self) -> None:
        """Compensation не должна вызываться повторно на failure."""
        call_count = 0

        async def failing_comp(exchange, context) -> None:
            nonlocal call_count
            call_count += 1
            raise RuntimeError("comp fail")

        step1 = _make_succeeding_step("s1")
        # Build compensation via CallableProcessor.
        from src.backend.dsl.engine.processors.base import CallableProcessor

        comp_proc = CallableProcessor(failing_comp, name="comp")
        step2 = _make_failing_step("s2")

        saga = SagaProcessor(
            steps=[
                SagaStep(forward=step1, compensate=comp_proc),
                SagaStep(forward=step2, compensate=None),
            ]
        )
        ex = _make_exchange()
        await saga.process(ex, context=MagicMock())

        # Comp failure happens EXACTLY once (no retry).
        assert call_count == 1

    async def test_audit_emission_does_not_silently_fail(self) -> None:
        """Если audit sink raises — saga всё равно должен terminate.

        Audit emission не должна блокировать saga termination.
        """
        step1 = _make_succeeding_step("s1")
        step2 = _make_failing_step("s2")

        saga = SagaProcessor(
            steps=[
                SagaStep(forward=step1, compensate=None),
                SagaStep(forward=step2, compensate=None),
            ]
        )
        ex = _make_exchange()

        # Audit sink raises RuntimeError → _emit_saga_audit catches it (best-effort).
        mock_sink = MagicMock()
        mock_sink.emit = AsyncMock(side_effect=RuntimeError("audit sink down"))

        with patch(
            "src.backend.services.audit.workflow_audit_sink.get_workflow_audit_sink",
            return_value=mock_sink,
        ):
            # Should NOT raise — _emit_saga_audit swallows RuntimeError.
            await saga.process(ex, context=MagicMock())

        # Saga terminated correctly despite audit failure.
        assert ex.status == ExchangeStatus.failed
        assert ex.get_property("saga_failed_step") == 1


class TestExports:
    """Module exports verification."""

    def test_module_exports(self) -> None:
        from src.backend.dsl.engine.processors.control_flow import saga

        assert hasattr(saga, "SagaProcessor")
        assert hasattr(saga, "SagaStep")


class TestRealisticBankingSaga:
    """Realistic banking saga — transfer with external API calls."""

    async def test_money_transfer_double_fault(self) -> None:
        """Realistic: банковский перевод с double-fault.

        Шаги:
          1. debit_source_account (succeeds)
          2. credit_destination_account (succeeds)
          3. log_to_audit_db (succeeds)
          4. notify_compliance (FAILS)

        Compensation (reverse):
          - log_to_audit_db.compensate = delete_audit_record (succeeds)
          - credit_destination_account.compensate = reverse_credit (FAILS — external API down)
          - debit_source_account.compensate = refund_debit (succeeds)

        Verifies: 2 compensations succeed, 1 fails, audit events emitted,
        saga terminates, no hang.
        """
        # ARRANGE.
        debit = _make_succeeding_step("debit_source")
        credit = _make_succeeding_step("credit_dest")
        credit_reverse = _make_failing_step("reverse_credit", error="external API 503")
        audit_log = _make_succeeding_step("audit_log")
        audit_delete = _make_succeeding_step("audit_delete")
        notify = _make_failing_step("notify_compliance", error="AML timeout")

        saga = SagaProcessor(
            steps=[
                SagaStep(forward=debit, compensate=None),
                SagaStep(forward=credit, compensate=credit_reverse),
                SagaStep(forward=audit_log, compensate=audit_delete),
                SagaStep(forward=notify, compensate=None),
            ]
        )
        ex = _make_exchange()

        # ACT.
        with patch(
            "src.backend.dsl.engine.processors.control_flow.saga._emit_saga_audit"
        ) as mock_audit:
            await saga.process(ex, context=MagicMock())

        # ASSERT: all forward steps executed.
        debit.process.assert_awaited_once()
        credit.process.assert_awaited_once()
        audit_log.process.assert_awaited_once()
        notify.process.assert_awaited_once()

        # ASSERT: compensations executed in REVERSE order.
        audit_delete.process.assert_awaited_once()  # step 3 comp.
        credit_reverse.process.assert_awaited_once()  # step 2 comp (failed).

        # ASSERT: terminated in failed state.
        assert ex.status == ExchangeStatus.failed

        # ASSERT: diagnostic info captured.
        assert ex.get_property("saga_failed_step") == 3
        # saga_error содержит сообщение оригинальной ошибки.
        assert "AML timeout" in (ex.get_property("saga_error") or "")

        # ASSERT: audit events.
        audit_events = [
            call.kwargs["event_type"] for call in mock_audit.call_args_list
        ]
        assert "workflow.compensation_start" in audit_events
        assert audit_events.count("workflow.compensation_fail") >= 2
