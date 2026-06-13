# ruff: noqa: S101
"""S106 W3 — tests для ``RouteBuilder.sub_workflow()`` + ``SubWorkflowProcessor``.

Покрытие:

* DSL registration (chainable, single processor instance);
* args validation (non-empty dict обязателен);
* ``to_spec()`` round-trip — defaults не в spec, custom values сериализуются;
* ``process()`` делегирует на ``InvokeWorkflowProcessor`` с
  зафиксированным ``mode="async-api"``;
* parent workflow/correlation_id auto-injection в args;
* Backend override — FakeWorkflowBackend используется напрямую.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.dsl.builders.base import RouteBuilder
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.sub_workflow import SubWorkflowProcessor


def _ex(body: Any = None, **props: Any) -> Exchange[Any]:
    ex = Exchange(in_message=Message(body=body, headers={}))
    for k, v in props.items():
        ex.set_property(k, v)
    return ex


def _ctx() -> ExecutionContext:
    return ExecutionContext()


def test_sub_workflow_dsl_registers_processor() -> None:
    """``RouteBuilder.sub_workflow(...)`` — добавляет SubWorkflowProcessor в pipeline."""
    b = RouteBuilder("test", source="kafka:orders")
    result = b.sub_workflow(
        "notifications.send_receipt",
        args={"order_id": "123", "channel": "email"},
    )
    assert isinstance(result, RouteBuilder)
    assert result is b
    assert len(b._processors) == 1
    p = b._processors[0]
    assert isinstance(p, SubWorkflowProcessor)
    assert p.workflow_name == "notifications.send_receipt"
    assert p.args == {"order_id": "123", "channel": "email"}


def test_sub_workflow_rejects_empty_args() -> None:
    """``SubWorkflowProcessor`` — пустой args запрещён (явная декомпозиция)."""
    with pytest.raises(ValueError, match="args обязательны"):
        SubWorkflowProcessor(name="x", args={})


def test_sub_workflow_chainable() -> None:
    """``sub_workflow()`` — chainable с другими DSL методами."""
    b = (
        RouteBuilder("test", source="kafka:orders")
        .set_property("workflow_id", "parent-123")
        .set_property("correlation_id", "corr-456")
        .sub_workflow("notifications.send", args={"order_id": "1"})
        .audit(action="sub_wf_dispatched")
    )
    # 2 set_property + 1 sub_workflow + 1 audit = 4 processors
    assert len(b._processors) == 4
    assert isinstance(b._processors[2], SubWorkflowProcessor)
    assert b._processors[3].__class__.__name__ == "AuditProcessor"


def test_sub_workflow_to_spec_minimal() -> None:
    """``to_spec()`` — минимальный YAML при дефолтных namespace/task_queue/etc."""
    p = SubWorkflowProcessor(
        name="notifications.send", args={"order_id": "1"}
    )
    spec = p.to_spec()
    assert spec == {
        "sub_workflow": {
            "name": "notifications.send",
            "args": {"order_id": "1"},
        }
    }


def test_sub_workflow_to_spec_preserves_custom_namespace() -> None:
    """``to_spec()`` — кастомный namespace попадает в spec."""
    p = SubWorkflowProcessor(
        name="x",
        args={"k": 1},
        namespace="tenant_a",
        task_queue="orders-queue",
        sub_workflow_id_property="child_id",
        result_property="subwf_result",
    )
    spec = p.to_spec()["sub_workflow"]
    assert spec["namespace"] == "tenant_a"
    assert spec["task_queue"] == "orders-queue"
    assert spec["sub_workflow_id_property"] == "child_id"
    assert spec["result_property"] == "subwf_result"


def test_sub_workflow_to_spec_omits_default_parent_properties() -> None:
    """``to_spec()`` — дефолтные parent_*_property не попадают в spec."""
    p = SubWorkflowProcessor(
        name="x", args={"k": 1}, parent_workflow_id_property="workflow_id"
    )
    spec = p.to_spec()["sub_workflow"]
    assert "parent_workflow_id_property" not in spec


def test_sub_workflow_to_spec_includes_custom_parent_properties() -> None:
    """``to_spec()`` — кастомные parent_*_property попадают в spec."""
    p = SubWorkflowProcessor(
        name="x",
        args={"k": 1},
        parent_workflow_id_property="parent_wf",
        parent_correlation_id_property="parent_corr",
    )
    spec = p.to_spec()["sub_workflow"]
    assert spec["parent_workflow_id_property"] == "parent_wf"
    assert spec["parent_correlation_id_property"] == "parent_corr"


@pytest.mark.asyncio
async def test_sub_workflow_process_uses_async_api_mode() -> None:
    """``process()`` — внутри вызывает ``InvokeWorkflowProcessor`` с mode=async-api.

    Проверяем через mock backend: ``start_workflow`` должен быть вызван ОДИН раз,
    ``await_completion`` — НЕ вызван (fire-and-forget = не ждём).
    Sub-workflow workflow_id — UUID, сгенерированный в processor (не из handle).
    """
    import uuid

    backend = MagicMock()
    backend.start_workflow = AsyncMock(
        return_value=MagicMock(workflow_id="ignored-handle-id")
    )
    backend.await_completion = AsyncMock()

    p = SubWorkflowProcessor(
        name="notifications.send",
        args={"order_id": "1"},
        backend=backend,
    )
    exchange = _ex(body={"unrelated": "x"})
    await p.process(exchange, _ctx())

    backend.start_workflow.assert_awaited_once()
    backend.await_completion.assert_not_awaited()
    wf_id = exchange.get_property("sub_workflow_id")
    # sub-workflow workflow_id — это UUID, сгенерированный в processor.
    # Backend handle возвращает свой id, но processor использует local
    # uuid4() для детерминированной sub-workflow маршрутизации.
    assert wf_id is not None
    uuid.UUID(wf_id)  # валидный UUID4
    assert wf_id != "ignored-handle-id"


@pytest.mark.asyncio
async def test_sub_workflow_injects_parent_ids_into_args() -> None:
    """``process()`` — parent_workflow_id/correlation_id прокидываются в args.

    Сценарий: parent workflow уже положил ``workflow_id=parent-123`` и
    ``correlation_id=corr-456`` в exchange.property. После ``sub_workflow`` —
    args ребёнка содержат ``_parent_workflow_id=parent-123`` и
    ``_parent_correlation_id=corr-456``.
    """
    backend = MagicMock()
    backend.start_workflow = AsyncMock(
        return_value=MagicMock(workflow_id="child-1")
    )

    p = SubWorkflowProcessor(
        name="x", args={"order_id": "1"}, backend=backend
    )
    exchange = _ex(
        workflow_id="parent-123", correlation_id="corr-456"
    )
    await p.process(exchange, _ctx())

    call_kwargs = backend.start_workflow.await_args.kwargs
    sent_input = call_kwargs["input"]
    assert sent_input["order_id"] == "1"
    assert sent_input["_parent_workflow_id"] == "parent-123"
    assert sent_input["_parent_correlation_id"] == "corr-456"


@pytest.mark.asyncio
async def test_sub_workflow_preserves_explicit_parent_in_args() -> None:
    """``process()`` — если user явно задал ``_parent_workflow_id`` в args,
    auto-injection НЕ перезаписывает (явное > неявное)."""
    backend = MagicMock()
    backend.start_workflow = AsyncMock(
        return_value=MagicMock(workflow_id="child-1")
    )

    p = SubWorkflowProcessor(
        name="x",
        args={"_parent_workflow_id": "explicit-parent"},
        backend=backend,
    )
    exchange = _ex(workflow_id="parent-123")
    await p.process(exchange, _ctx())

    sent_input = backend.start_workflow.await_args.kwargs["input"]
    assert sent_input["_parent_workflow_id"] == "explicit-parent"


@pytest.mark.asyncio
async def test_sub_workflow_no_parent_ids_in_exchange() -> None:
    """``process()`` — если parent ids отсутствуют, args не загрязняются мусором."""
    backend = MagicMock()
    backend.start_workflow = AsyncMock(
        return_value=MagicMock(workflow_id="child-1")
    )

    p = SubWorkflowProcessor(
        name="x", args={"order_id": "1"}, backend=backend
    )
    exchange = _ex()
    await p.process(exchange, _ctx())

    sent_input = backend.start_workflow.await_args.kwargs["input"]
    assert "_parent_workflow_id" not in sent_input
    assert "_parent_correlation_id" not in sent_input


def test_sub_workflow_processor_kind_for_dispatch() -> None:
    """``SubWorkflowProcessor`` — имеет ``name`` (используется в pipeline dispatch)."""
    p = SubWorkflowProcessor(name="x", args={"k": 1})
    assert p.name == "sub_workflow:x"
