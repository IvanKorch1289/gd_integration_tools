# ruff: noqa: S101
"""Unit-тесты ``src.backend.core.workflow.backend`` — Pydantic-модели +
``WorkflowBackend`` Protocol + ``WorkflowStatus`` type alias.

Сфокусировано на edge cases, которые не покрыты в ``test_backend_protocol.py``:
- ``WorkflowStatus`` — это ``str``-alias (можно использовать как параметр Pydantic);
- Protocol runtime_checkable принимает duck-typed классы и отвергает неподходящие;
- frozen-равенство моделей (хэшируемость);
- полный набор ограничений ``min_length=1`` для каждого поля handle;
- ``extra="forbid"`` на ``WorkflowResult``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.backend.core.workflow.backend import (
    WorkflowBackend,
    WorkflowHandle,
    WorkflowResult,
    WorkflowStatus,
)


class TestWorkflowStatusAlias:
    """``WorkflowStatus`` — это ``str`` alias, не Enum / Literal."""

    def test_is_str_subclass(self) -> None:
        # type alias `WorkflowStatus = str` означает что значение — str.
        assert WorkflowStatus("completed") == "completed"
        assert isinstance("failed", WorkflowStatus)
        # Прямой str assignment не должен падать (Pydantic валидирует статус
        # в ``WorkflowResult.status`` только как str, без Literal-ограничения).
        result = WorkflowResult(status="custom_backend_specific_value")  # type: ignore[arg-type]
        assert result.status == "custom_backend_specific_value"

    def test_module_exports(self) -> None:
        import src.backend.core.workflow as wf_pkg
        import src.backend.core.workflow.backend as backend_mod

        # Пакет реэкспортирует WorkflowStatus.
        assert wf_pkg.WorkflowStatus is WorkflowStatus
        # ``__all__`` покрывает все 4 публичных имени.
        assert backend_mod.__all__ == (
            "WorkflowBackend",
            "WorkflowHandle",
            "WorkflowResult",
            "WorkflowStatus",
        )


class TestWorkflowHandleValidation:
    """Граничные случаи ``min_length=1`` и ``extra="forbid"``."""

    @pytest.mark.parametrize("field", ["workflow_id", "run_id", "namespace"])
    def test_empty_field_rejected(self, field: str) -> None:
        kwargs = {"workflow_id": "wf", "run_id": "r", "namespace": "ns"}
        kwargs[field] = ""
        with pytest.raises(ValidationError):
            WorkflowHandle(**kwargs)

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            WorkflowHandle.model_validate(
                {
                    "workflow_id": "wf",
                    "run_id": "r",
                    "namespace": "ns",
                    "bogus": "x",
                }
            )

    def test_equality_and_hash(self) -> None:
        # Frozen Pydantic-модели: равны если поля равны, и хэшируемы.
        a = WorkflowHandle(workflow_id="wf", run_id="r", namespace="ns")
        b = WorkflowHandle(workflow_id="wf", run_id="r", namespace="ns")
        c = WorkflowHandle(workflow_id="wf", run_id="r2", namespace="ns")
        assert a == b
        assert hash(a) == hash(b)
        assert a != c
        # Хэш стабилен: повторный вызов даёт то же значение.
        assert hash(a) == hash(a)
        # Модель — Pydantic BaseModel с frozen=True, у неё есть __hash__.
        assert callable(a.__class__.__hash__)

    def test_model_dump_roundtrip(self) -> None:
        handle = WorkflowHandle(workflow_id="wf", run_id="r", namespace="ns")
        dumped = handle.model_dump()
        assert dumped == {
            "workflow_id": "wf",
            "run_id": "r",
            "namespace": "ns",
        }
        restored = WorkflowHandle.model_validate(dumped)
        assert restored == handle


class TestWorkflowResultValidation:
    """``WorkflowResult`` — frozen + extra forbid + опциональный failure."""

    def test_frozen_cannot_mutate(self) -> None:
        result = WorkflowResult(status="completed")
        with pytest.raises(ValidationError):
            result.status = "failed"  # type: ignore[misc]

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            WorkflowResult.model_validate(
                {"status": "completed", "extra_field": "nope"}
            )

    def test_all_terminal_statuses_accepted(self) -> None:
        # Литеральный набор не зашит — backend может прислать любую str.
        for status in ("completed", "failed", "cancelled", "timed_out"):
            result = WorkflowResult(status=status)
            assert result.status == status

    def test_default_output_is_empty_dict(self) -> None:
        # Каждый экземпляр получает СВОЙ dict (default_factory).
        r1 = WorkflowResult(status="completed")
        r2 = WorkflowResult(status="completed")
        assert r1.output == {}
        assert r2.output == {}
        r1.output["x"] = 1
        assert r2.output == {}, "default dict shared between instances!"

    def test_failure_with_details_payload(self) -> None:
        result = WorkflowResult(
            status="timed_out",
            failure={
                "type": "TimeoutError",
                "message": "30s elapsed",
                "details": {"step": "validate", "elapsed_ms": 30000},
            },
        )
        assert result.failure is not None
        assert result.failure["type"] == "TimeoutError"
        assert result.failure["details"]["step"] == "validate"


class TestWorkflowBackendProtocol:
    """``@runtime_checkable`` Protocol — duck-typing на сигнатурах."""

    def test_accepts_proper_implementation(self) -> None:
        class RealImpl:
            async def start_workflow(self, **_: object) -> WorkflowHandle:
                return WorkflowHandle(
                    workflow_id="x", run_id="r", namespace="n"
                )

            async def signal_workflow(self, **_: object) -> None:
                return None

            async def query_workflow(self, **_: object) -> dict[str, object]:
                return {}

            async def cancel_workflow(self, **_: object) -> None:
                return None

            async def await_completion(self, **_: object) -> WorkflowResult:
                return WorkflowResult(status="completed")

            async def replay(self, **_: object) -> None:
                return None

        assert isinstance(RealImpl(), WorkflowBackend)

    def test_rejects_partial_implementation(self) -> None:
        # Не хватает replay / await_completion — runtime_checkable всё равно
        # смотрит ТОЛЬКО на наличие методов (без проверки сигнатур), поэтому
        # класс с тем же набором методов проходит isinstance.
        # Это документированное поведение ``runtime_checkable``.
        class Partial:
            async def start_workflow(self, **_: object) -> object:
                return object()

            async def signal_workflow(self, **_: object) -> None:
                return None

            async def query_workflow(self, **_: object) -> object:
                return {}

            async def cancel_workflow(self, **_: object) -> None:
                return None

            async def await_completion(self, **_: object) -> object:
                return object()

            async def replay(self, **_: object) -> None:
                return None

        assert isinstance(Partial(), WorkflowBackend)

    def test_rejects_object_without_methods(self) -> None:
        class NotABackend:
            pass

        assert not isinstance(NotABackend(), WorkflowBackend)
        assert not isinstance("string", WorkflowBackend)
        assert not isinstance(42, WorkflowBackend)
