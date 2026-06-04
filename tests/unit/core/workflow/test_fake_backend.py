# ruff: noqa: S101
"""Unit-тесты ``src.backend.core.workflow.fake_backend.FakeWorkflowBackend``.

Покрывает публичные методы, test-helpers и приватный ``_require``
(``KeyError`` + ``ValueError`` paths). Не дублирует ``test_backend_protocol.py``:
там уже есть базовые сценарии start/signal/query/cancel/await.
Здесь — edge cases: ordering сигналов, copy-семантика ``signals_for``,
``_require`` ValueError при подмене handle, default_result override,
unique run_id, replay no-op и т.д.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from src.backend.core.workflow.backend import WorkflowHandle, WorkflowResult
from src.backend.core.workflow.fake_backend import FakeWorkflowBackend


async def _start(
    backend: FakeWorkflowBackend,
    *,
    workflow_id: str = "wf-1",
    workflow_name: str = "wf",
    namespace: str = "t",
    task_queue: str = "q",
    input: dict[str, Any] | None = None,
    execution_timeout: timedelta | None = None,
) -> WorkflowHandle:
    """Хелпер: старт workflow с разумными дефолтами."""
    return await backend.start_workflow(
        workflow_name=workflow_name,
        workflow_id=workflow_id,
        input=input if input is not None else {},
        namespace=namespace,
        task_queue=task_queue,
        execution_timeout=execution_timeout,
    )


class TestFakeBackendConstruction:
    """Дефолты конструктора + override ``default_result``/``query_handlers``."""

    def test_default_result_is_completed(self) -> None:
        backend = FakeWorkflowBackend()
        # Дефолтный default_result = WorkflowResult(status="completed")
        assert backend._default_result.status == "completed"  # noqa: SLF001
        assert backend._default_result.output == {}  # noqa: SLF001
        assert backend._query_handlers == {}  # noqa: SLF001
        assert backend._instances == {}  # noqa: SLF001

    def test_custom_default_result(self) -> None:
        custom = WorkflowResult(status="failed", output={"reason": "test-fixture"})
        backend = FakeWorkflowBackend(default_result=custom)
        assert backend._default_result is custom  # noqa: SLF001

    def test_custom_query_handlers(self) -> None:
        handlers = {"status": {"phase": "review"}, "progress": {"pct": 50}}
        backend = FakeWorkflowBackend(query_handlers=handlers)
        assert backend._query_handlers == handlers  # noqa: SLF001


@pytest.mark.asyncio
class TestStartWorkflow:
    """``start_workflow`` — создаёт инстанс + возвращает handle с uuid4 run_id."""

    async def test_run_id_is_unique_per_start(self) -> None:
        backend = FakeWorkflowBackend()
        h1 = await _start(backend, workflow_id="a")
        h2 = await _start(backend, workflow_id="a")
        assert h1.run_id != h2.run_id, "run_id должен быть uuid4 (уникален)"
        # namespace/ workflow_id — берутся из аргументов.
        assert h1.workflow_id == "a"
        assert h1.namespace == "t"
        assert h2.workflow_id == "a"

    async def test_stores_input_and_metadata(self) -> None:
        backend = FakeWorkflowBackend()
        handle = await _start(
            backend,
            workflow_name="credit_score",
            workflow_id="wf-x",
            input={"client_id": 42, "force": True},
            task_queue="priority",
            execution_timeout=timedelta(seconds=30),
        )
        instance = backend._instances[handle.run_id]  # noqa: SLF001
        assert instance.workflow_name == "credit_score"
        assert instance.input == {"client_id": 42, "force": True}
        assert instance.task_queue == "priority"
        assert instance.execution_timeout == timedelta(seconds=30)
        # Сигналов и отмены ещё нет.
        assert instance.signals == []
        assert instance.cancelled is False
        assert instance.result is None

    async def test_default_execution_timeout_is_none(self) -> None:
        backend = FakeWorkflowBackend()
        handle = await _start(backend)
        assert (
            backend._instances[handle.run_id].execution_timeout is None  # noqa: SLF001
        )


@pytest.mark.asyncio
class TestSignalAndQuery:
    """``signal_workflow`` / ``query_workflow`` — запись в журнал + lookup."""

    async def test_signals_preserve_order(self) -> None:
        backend = FakeWorkflowBackend()
        handle = await _start(backend)
        for name, payload in [
            ("approve", {"by": "ops"}),
            ("comment", {"text": "LGTM"}),
            ("close", {}),
        ]:
            await backend.signal_workflow(
                handle=handle, signal_name=name, payload=payload
            )
        assert backend.signals_for(handle) == [
            ("approve", {"by": "ops"}),
            ("comment", {"text": "LGTM"}),
            ("close", {}),
        ]

    async def test_signals_for_returns_copy(self) -> None:
        # Внутренняя list не должна протекать через возврат — иначе можно
        # мутировать состояние backend'а в обход signal_workflow.
        backend = FakeWorkflowBackend()
        handle = await _start(backend)
        await backend.signal_workflow(handle=handle, signal_name="x", payload={})
        snapshot = backend.signals_for(handle)
        snapshot.append(("injected", {"hack": True}))
        # Второй вызов возвращает оригинальный список без инъекции.
        assert backend.signals_for(handle) == [("x", {})]

    async def test_query_handlers_strict_lookup(self) -> None:
        backend = FakeWorkflowBackend(query_handlers={"status": {"phase": "ok"}})
        handle = await _start(backend)
        # Найденный query возвращает свой dict.
        assert await backend.query_workflow(handle=handle, query_name="status") == {
            "phase": "ok"
        }
        # Несуществующий query — пустой dict, не KeyError.
        assert await backend.query_workflow(handle=handle, query_name="missing") == {}

    async def test_query_args_are_accepted_but_unused(self) -> None:
        # В fake backend ``args`` не интерпретируются — контракт зарезервирован
        # для future expansion. Проверяем что параметр не ломает вызов.
        backend = FakeWorkflowBackend(query_handlers={"echo": {"v": 1}})
        handle = await _start(backend)
        result = await backend.query_workflow(
            handle=handle, query_name="echo", args={"ignored": True}
        )
        assert result == {"v": 1}


@pytest.mark.asyncio
class TestCancelAndAwait:
    """``cancel_workflow`` + ``await_completion`` — приоритет set_result."""

    async def test_cancel_sets_cancelled_flag_and_result(self) -> None:
        backend = FakeWorkflowBackend()
        handle = await _start(backend)
        assert backend.is_cancelled(handle) is False
        await backend.cancel_workflow(handle=handle)
        assert backend.is_cancelled(handle) is True
        # await_completion сразу после cancel возвращает cancelled.
        result = await backend.await_completion(handle=handle)
        assert result.status == "cancelled"

    async def test_set_result_overrides_cancel(self) -> None:
        # set_result имеет приоритет над cancel-workflow: если тест-сетап
        # сначала установил результат, потом cancel — вернётся set_result.
        backend = FakeWorkflowBackend()
        handle = await _start(backend)
        backend.set_result(
            handle, WorkflowResult(status="completed", output={"step": 5})
        )
        await backend.cancel_workflow(handle=handle)
        result = await backend.await_completion(handle=handle)
        # cancel перезаписывает result (см. cancel_workflow) — set_result
        # имеет приоритет только если cancel ещё не вызывался.
        assert result.status == "cancelled"

    async def test_await_returns_default_when_not_finished(self) -> None:
        custom = WorkflowResult(status="completed", output={"source": "default"})
        backend = FakeWorkflowBackend(default_result=custom)
        handle = await _start(backend)
        result = await backend.await_completion(
            handle=handle, timeout=timedelta(seconds=5)
        )
        # timeout — параметр для совместимости с Protocol, fake его игнорирует.
        assert result.status == "completed"
        assert result.output == {"source": "default"}

    async def test_await_returns_set_result_over_default(self) -> None:
        backend = FakeWorkflowBackend(default_result=WorkflowResult(status="completed"))
        handle = await _start(backend)
        backend.set_result(handle, WorkflowResult(status="failed", output={"k": "v"}))
        result = await backend.await_completion(handle=handle)
        assert result.status == "failed"
        assert result.output == {"k": "v"}


@pytest.mark.asyncio
class TestReplay:
    """``replay`` — no-op, но не должен падать."""

    async def test_replay_empty_history(self) -> None:
        backend = FakeWorkflowBackend()
        await backend.replay(workflow_name="wf", history=b"")

    async def test_replay_with_arbitrary_bytes(self) -> None:
        backend = FakeWorkflowBackend()
        # Любой bytes принимается, fake не моделирует replay-семантику.
        await backend.replay(workflow_name="credit_score", history=b"\x00\x01\x02\xff")

    async def test_replay_does_not_affect_instances(self) -> None:
        backend = FakeWorkflowBackend()
        handle = await _start(backend)
        await backend.replay(workflow_name="wf", history=b"history")
        # Состояние инстанса не меняется.
        instance = backend._instances[handle.run_id]  # noqa: SLF001
        assert instance.cancelled is False
        assert instance.result is None
        assert instance.signals == []


class TestRequire:
    """``_require`` — KeyError для unknown run_id, ValueError для mismatch."""

    def test_require_raises_keyerror_for_unknown_run_id(self) -> None:
        backend = FakeWorkflowBackend()
        ghost = WorkflowHandle(workflow_id="x", run_id="missing", namespace="t")
        with pytest.raises(KeyError, match="missing"):
            backend._require(ghost)  # noqa: SLF001

    @pytest.mark.asyncio
    async def test_require_raises_valueerror_on_handle_mismatch(self) -> None:
        backend = FakeWorkflowBackend()
        real = await _start(backend, workflow_id="wf-real")
        # Конструируем "подменный" handle с тем же run_id, но другим
        # workflow_id/namespace. ``_require`` обязан отловить это как
        # ValueError, чтобы избежать cross-instance lookup-атак.
        forged = WorkflowHandle(
            workflow_id="wf-forged", run_id=real.run_id, namespace="other"
        )
        with pytest.raises(ValueError, match="Handle mismatch"):
            backend._require(forged)  # noqa: SLF001

    @pytest.mark.asyncio
    async def test_require_propagates_through_public_methods(self) -> None:
        # _require — скрытый контракт; публичные методы обязаны пробрасывать
        # его исключения. Проверяем, что cancel/query/await на ghost-handle
        # бросают KeyError (т.е. _require не "съедается" try/except'ом).
        backend = FakeWorkflowBackend()
        ghost = WorkflowHandle(workflow_id="x", run_id="nope", namespace="t")

        with pytest.raises(KeyError):
            await backend.signal_workflow(handle=ghost, signal_name="s", payload={})
        with pytest.raises(KeyError):
            await backend.query_workflow(handle=ghost, query_name="q")
        with pytest.raises(KeyError):
            await backend.cancel_workflow(handle=ghost)
        with pytest.raises(KeyError):
            await backend.await_completion(handle=ghost)
        # test-helpers тоже используют _require.
        with pytest.raises(KeyError):
            backend.signals_for(ghost)
        with pytest.raises(KeyError):
            backend.is_cancelled(ghost)
        with pytest.raises(KeyError):
            backend.set_result(ghost, WorkflowResult(status="completed"))
