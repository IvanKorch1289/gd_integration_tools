"""S55 W2 — saga.py part of control_flow decomp.

Classes: SagaStep, SagaProcessor.
Funcs: _serialize_sub, _emit_saga_audit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus
from src.backend.dsl.engine.processors.base import BaseProcessor

_cf_logger = get_logger("dsl.control_flow")


@dataclass
class SagaStep:
    """Шаг саги: forward-действие + компенсация при откате.

    .. note::
        S137 W3 factcheck: added ``@dataclass`` decorator — 3 failing
        tests in test_saga_lra_mixin.py (SagaStep() takes no arguments)
        root cause: class had type-annotated attrs but no ``__init__``.
    """

    forward: BaseProcessor
    compensate: BaseProcessor | None = None


class SagaProcessor(BaseProcessor):
    """Saga-паттерн: выполняет шаги последовательно с откатом.

    Если шаг ``N`` падает — запускает компенсации шагов
    ``N-1, N-2, ..., 0`` в обратном порядке.
    """

    def __init__(self, steps: list[SagaStep], *, name: str | None = None) -> None:
        super().__init__(name=name or f"saga({len(steps)} steps)")
        self._steps = steps

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        completed_steps: list[SagaStep] = []
        saga_workflow_id = (
            exchange.get_property("saga_workflow_id")
            or exchange.get_property("workflow_id")
            or context.route_id
            or "saga"
        )

        for i, step in enumerate(self._steps):
            try:
                await step.forward.process(exchange, context)

                if exchange.status == ExchangeStatus.failed:
                    raise RuntimeError(exchange.error or f"Step {i} failed")

                completed_steps.append(step)
            except Exception as exc:
                _cf_logger.error("Saga step %d failed: %s. Compensating...", i, exc)
                exchange.set_property("saga_failed_step", i)
                exchange.set_property("saga_error", str(exc))

                await _emit_saga_audit(
                    event_type="workflow.compensation_start",
                    workflow_id=str(saga_workflow_id),
                    payload={
                        "failed_step": i,
                        "error": str(exc),
                        "steps_to_compensate": len(completed_steps),
                    },
                )

                any_failed = False
                for comp_step in reversed(completed_steps):
                    if comp_step.compensate is not None:
                        try:
                            exchange.status = ExchangeStatus.processing
                            exchange.error = None
                            await comp_step.compensate.process(exchange, context)
                        except Exception as comp_exc:
                            any_failed = True
                            _cf_logger.error("Saga compensation failed: %s", comp_exc)
                            await _emit_saga_audit(
                                event_type="workflow.compensation_fail",
                                workflow_id=str(saga_workflow_id),
                                payload={
                                    "step": comp_step.forward.name,
                                    "error": str(comp_exc),
                                },
                            )

                await _emit_saga_audit(
                    event_type=(
                        "workflow.compensation_fail"
                        if any_failed
                        else "workflow.compensation_complete"
                    ),
                    workflow_id=str(saga_workflow_id),
                    payload={
                        "failed_step": i,
                        "compensated_count": len(completed_steps),
                    },
                )

                exchange.fail(f"Saga failed at step {i}: {exc}")
                return

        exchange.set_property("saga_completed", True)

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализует Saga-шаги в YAML-spec.

        Каждый шаг сериализуется как ``{forward: {...}, compensate: {...}}``;
        если хоть один step не сериализуется (callable forward/compensate)
        — возвращается ``None`` для всего Saga.
        """
        steps_spec: list[dict[str, Any]] = []
        for step in self._steps:
            forward_spec = step.forward.to_spec()
            if forward_spec is None:
                return None
            entry: dict[str, Any] = {"forward": forward_spec}
            if step.compensate is not None:
                comp_spec = step.compensate.to_spec()
                if comp_spec is None:
                    return None
                entry["compensate"] = comp_spec
            steps_spec.append(entry)
        return {"saga": {"steps": steps_spec}}


def _serialize_sub(procs: list[BaseProcessor]) -> list[dict[str, Any]] | None:
    """Сериализует список sub-processors через ``to_spec``.

    Если хотя бы один child возвращает ``None`` (например, callable
    payload_factory), весь sub-pipeline считается несериализуемым —
    возвращаем ``None``, чтобы родительский ``to_spec`` тоже отдал ``None``.

    Args:
        procs: Дочерние процессоры sub-pipeline.

    Returns:
        Список dict-spec'ов либо ``None``.
    """
    out: list[dict[str, Any]] = []
    for p in procs:
        spec = p.to_spec()
        if spec is None:
            return None
        out.append(spec)
    return out


async def _emit_saga_audit(
    *, event_type: str, workflow_id: str, payload: dict[str, Any]
) -> None:
    """Sprint 12 K3 W6 — best-effort emit saga compensation events.

    Никогда не пробрасывает исключения: пропадание audit-связи не
    должно ломать основной saga-flow.
    """
    try:
        from src.backend.services.audit.workflow_audit_sink import (
            get_workflow_audit_sink,
        )

        sink = get_workflow_audit_sink()
        if sink is None:
            return
        await sink.emit(
            event_type=event_type,
            workflow_id=workflow_id,
            tenant_id=None,
            payload={"caller": "dsl.saga", **payload},
        )
    except Exception as _:
        pass
