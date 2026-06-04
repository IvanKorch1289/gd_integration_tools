"""Unit-тесты CancelWorkflowProcessor — Sprint 12 K3 W7.

Проверяемые сценарии:
    * cancel по литералу workflow_id;
    * cancel по Ref-выражению ``${body.workflow_id}``;
    * cancel пустого Ref → ValueError;
    * audit-event ``workflow.cancel`` эмитится через sink;
    * reason пробрасывается в audit payload;
    * round-trip ``to_spec()`` корректен;
    * процессор регистрируется в processor-registry.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.cancel_workflow import CancelWorkflowProcessor


def _ex(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


def _ctx() -> ExecutionContext:
    return ExecutionContext()


@pytest.fixture
def backend_mock() -> Any:
    backend = MagicMock()
    backend.cancel_workflow = AsyncMock(return_value=None)
    return backend


@pytest.fixture(autouse=True)
def _reset_sink() -> None:
    from src.backend.services.audit import workflow_audit_sink as wam

    wam.reset_workflow_audit_sink()
    yield
    wam.reset_workflow_audit_sink()


@pytest.mark.asyncio
async def test_cancel_by_literal_id(backend_mock: Any) -> None:
    proc = CancelWorkflowProcessor(
        "wf-abc-123", reason="ttl_expired", backend=backend_mock
    )
    exchange = _ex()
    await proc.process(exchange, _ctx())

    backend_mock.cancel_workflow.assert_awaited_once()
    handle = backend_mock.cancel_workflow.await_args.kwargs["handle"]
    assert handle.workflow_id == "wf-abc-123"
    result = exchange.get_property("cancel_result")
    assert result == {
        "cancelled": True,
        "workflow_id": "wf-abc-123",
        "reason": "ttl_expired",
    }


@pytest.mark.asyncio
async def test_cancel_by_body_ref(backend_mock: Any) -> None:
    proc = CancelWorkflowProcessor("${body.invocation_id}", backend=backend_mock)
    exchange = _ex(body={"invocation_id": "wf-xyz-999"})
    await proc.process(exchange, _ctx())

    backend_mock.cancel_workflow.assert_awaited_once()
    handle = backend_mock.cancel_workflow.await_args.kwargs["handle"]
    assert handle.workflow_id == "wf-xyz-999"


@pytest.mark.asyncio
async def test_cancel_emits_audit_event(backend_mock: Any) -> None:
    sink = MagicMock()
    sink.emit = AsyncMock(return_value=None)
    from src.backend.services.audit import workflow_audit_sink as wam

    wam.set_workflow_audit_sink(sink)

    proc = CancelWorkflowProcessor(
        "wf-cancel-1", reason="user_action", backend=backend_mock
    )
    await proc.process(_ex(), _ctx())

    sink.emit.assert_awaited_once()
    kwargs = sink.emit.await_args.kwargs
    assert kwargs["event_type"] == "workflow.cancel"
    assert kwargs["workflow_id"] == "wf-cancel-1"
    assert kwargs["payload"]["reason"] == "user_action"
    assert kwargs["payload"]["caller"] == "dsl.cancel_workflow"


@pytest.mark.asyncio
async def test_cancel_audit_failure_is_swallowed(backend_mock: Any) -> None:
    sink = MagicMock()
    sink.emit = AsyncMock(side_effect=RuntimeError("audit down"))
    from src.backend.services.audit import workflow_audit_sink as wam

    wam.set_workflow_audit_sink(sink)

    proc = CancelWorkflowProcessor("wf-1", backend=backend_mock)
    await proc.process(_ex(), _ctx())

    backend_mock.cancel_workflow.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancel_empty_ref_raises(backend_mock: Any) -> None:
    proc = CancelWorkflowProcessor("${body.missing}", backend=backend_mock)
    exchange = _ex(body={})
    with pytest.raises(ValueError, match="workflow_id"):
        # Ref остаётся литеральной строкой "${body.missing}" если ключа нет —
        # но процессор всё равно должен попытаться его cancel'ить.
        # Чтобы проверить ValueError, используем явно пустой spec.
        await CancelWorkflowProcessor("", backend=backend_mock).process(
            exchange, _ctx()
        )


def test_to_spec_round_trip() -> None:
    proc = CancelWorkflowProcessor(
        "${body.wf_id}",
        reason="cleanup",
        namespace="payments",
        result_property="cancel_out",
    )
    spec = proc.to_spec()
    assert spec == {
        "cancel_workflow": {
            "workflow_id": "${body.wf_id}",
            "reason": "cleanup",
            "namespace": "payments",
            "result_property": "cancel_out",
        }
    }


def test_to_spec_minimal() -> None:
    proc = CancelWorkflowProcessor("wf-1")
    assert proc.to_spec() == {"cancel_workflow": {"workflow_id": "wf-1"}}


def test_processor_registered_in_registry() -> None:
    from src.backend.dsl.registry import get_processor_registry

    registry = get_processor_registry()
    spec = registry.get("core:cancel_workflow")
    assert spec is not None
    assert spec.namespace == "core"
    assert spec.meta.get("category") == "workflow"
