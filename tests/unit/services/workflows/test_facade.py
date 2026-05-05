# ruff: noqa: S101
"""Тесты `WorkflowFacade` capability-gate (Wave D.2 / ADR-045)."""

from __future__ import annotations

import pytest

from src.backend.core.security.capabilities import (
    CapabilityDeniedError,
    CapabilityGate,
    CapabilityRef,
)
from src.backend.core.workflow import FakeWorkflowBackend, WorkflowResult
from src.backend.services.workflows import WorkflowFacade


@pytest.fixture
def gate() -> CapabilityGate:
    return CapabilityGate()


@pytest.fixture
def facade(gate: CapabilityGate) -> WorkflowFacade:
    backend = FakeWorkflowBackend()
    return WorkflowFacade(backend=backend, capability_gate=gate)


@pytest.mark.asyncio
class TestStartCapabilityGate:
    async def test_denied_without_declaration(self, facade: WorkflowFacade) -> None:
        with pytest.raises(CapabilityDeniedError):
            await facade.start(
                caller="ext.credit_score",
                workflow_name="credit",
                workflow_id="credit.score.42",
                input={},
                namespace="bank-a",
                task_queue="default",
            )

    async def test_granted_when_capability_declared(
        self, facade: WorkflowFacade, gate: CapabilityGate
    ) -> None:
        gate.declare(
            "ext.credit_score",
            [CapabilityRef(name="workflow.start", scope="credit.score.*")],
        )
        handle = await facade.start(
            caller="ext.credit_score",
            workflow_name="credit",
            workflow_id="credit.score.42",
            input={"client_id": 7},
            namespace="bank-a",
            task_queue="default",
        )
        assert handle.workflow_id == "credit.score.42"
        assert handle.namespace == "bank-a"

    async def test_scope_mismatch_denied(
        self, facade: WorkflowFacade, gate: CapabilityGate
    ) -> None:
        gate.declare(
            "ext.credit_score",
            [CapabilityRef(name="workflow.start", scope="credit.score.*")],
        )
        with pytest.raises(CapabilityDeniedError):
            await facade.start(
                caller="ext.credit_score",
                workflow_name="credit",
                workflow_id="loan.application.99",
                input={},
                namespace="bank-a",
                task_queue="default",
            )


@pytest.mark.asyncio
class TestSignalCapabilityGate:
    async def test_signal_gate(
        self, facade: WorkflowFacade, gate: CapabilityGate
    ) -> None:
        gate.declare(
            "ext.credit_score",
            [
                CapabilityRef(name="workflow.start", scope="credit.score.*"),
                CapabilityRef(name="workflow.signal", scope="credit.score.*"),
            ],
        )
        handle = await facade.start(
            caller="ext.credit_score",
            workflow_name="credit",
            workflow_id="credit.score.42",
            input={},
            namespace="bank-a",
            task_queue="default",
        )
        await facade.signal(
            caller="ext.credit_score", handle=handle, signal_name="approve", payload={}
        )

    async def test_signal_denied_without_signal_capability(
        self, facade: WorkflowFacade, gate: CapabilityGate
    ) -> None:
        gate.declare(
            "ext.credit_score",
            [CapabilityRef(name="workflow.start", scope="credit.score.*")],
        )
        handle = await facade.start(
            caller="ext.credit_score",
            workflow_name="credit",
            workflow_id="credit.score.42",
            input={},
            namespace="bank-a",
            task_queue="default",
        )
        with pytest.raises(CapabilityDeniedError):
            await facade.signal(
                caller="ext.credit_score",
                handle=handle,
                signal_name="approve",
                payload={},
            )


@pytest.mark.asyncio
class TestAwaitCompletionNoGate:
    async def test_await_does_not_check_capability(
        self, facade: WorkflowFacade, gate: CapabilityGate
    ) -> None:
        gate.declare(
            "ext.credit_score",
            [CapabilityRef(name="workflow.start", scope="credit.score.*")],
        )
        handle = await facade.start(
            caller="ext.credit_score",
            workflow_name="credit",
            workflow_id="credit.score.42",
            input={},
            namespace="bank-a",
            task_queue="default",
        )
        # Без declared signal — но await должен проходить без gate-check.
        result = await facade.await_completion(handle=handle)
        assert isinstance(result, WorkflowResult)
        assert result.status == "completed"
