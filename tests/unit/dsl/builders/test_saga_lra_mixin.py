"""Unit-тесты ``SagaLRAMixin``.

Покрывают fluent-интерфейс, тип добавленного процессора
и передачу ``workflow_id`` / ``run_id``.
"""

# ruff: noqa: S101

from __future__ import annotations

from unittest.mock import MagicMock

from src.backend.dsl.builders.base import RouteBuilder
from src.backend.dsl.engine.processors.control_flow import SagaStep
from src.backend.dsl.engine.processors.saga_lra import SagaLRAProcessor


class TestSagaLRAMixin:
    def test_returns_route_builder(self) -> None:
        step = SagaStep(forward=MagicMock(), compensate=None)
        builder = RouteBuilder.from_("test.saga_lra", source="internal:test")
        result = builder.saga_lra([step])
        assert isinstance(result, RouteBuilder)
        assert result is builder

    def test_adds_saga_lra_processor(self) -> None:
        step = SagaStep(forward=MagicMock(), compensate=None)
        pipeline = (
            RouteBuilder.from_("test.saga_lra", source="internal:test")
            .saga_lra([step], workflow_id="wf1", run_id="r1")
            .build()
        )
        assert len(pipeline.processors) == 1
        proc = pipeline.processors[0]
        assert isinstance(proc, SagaLRAProcessor)
        assert proc._workflow_id == "wf1"
        assert proc._run_id == "r1"

    def test_to_spec(self) -> None:
        forward = MagicMock()
        forward.to_spec.return_value = None
        step = SagaStep(forward=forward, compensate=None)
        pipeline = (
            RouteBuilder.from_("test.saga_lra", source="internal:test")
            .saga_lra([step], workflow_id="wf1", run_id="r1")
            .build()
        )
        spec = pipeline.processors[0].to_spec()
        # forward.to_spec вернул None → весь spec None
        assert spec is None
