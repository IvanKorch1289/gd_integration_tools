"""Saga LRA (Long Running Action) processor with PostgreSQL persistence.

Extends in-memory :class:`SagaProcessor` with durable checkpoints
and compensation tracking via :class:`WorkflowStateRepository`.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.engine.processors.control_flow import SagaStep, _emit_saga_audit

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext

__all__ = ("SagaLRAProcessor",)

_lra_logger = get_logger("dsl.saga_lra")

# lazy-evaluated at module level for testability
_get_smart_session_manager = None


def _lazy_get_smart_session_manager():
    global _get_smart_session_manager
    if _get_smart_session_manager is None:
        from src.backend.infrastructure.database.database import (
            get_smart_session_manager,
        )

        _get_smart_session_manager = get_smart_session_manager
    return _get_smart_session_manager


class _RepoProxy:
    """Per-operation session wrapper around ``WorkflowStateRepository``.

    Each ``load`` / ``save`` acquires a fresh write-session, commits,
    and closes — saga steps never hold DB transactions open.
    """

    def __init__(self, sm: Any, repo_cls: Any) -> None:
        self._sm = sm
        self._repo_cls = repo_cls

    async def load(self, workflow_id: uuid.UUID, run_id: str) -> Any | None:
        async with self._sm.acquire(mode="write") as session:
            repo = self._repo_cls(session)
            result = await repo.load(workflow_id, run_id)
            await session.commit()
            return result

    async def save(self, **kwargs: Any) -> Any:
        async with self._sm.acquire(mode="write") as session:
            repo = self._repo_cls(session)
            result = await repo.save(**kwargs)
            await session.commit()
            return result


class SagaLRAProcessor(BaseProcessor):
    """Saga-паттерн с persistent checkpoints и компенсацией (LRA).

    Args:
        steps: Список :class:`SagaStep` (forward + compensate).
        workflow_id: Опц. UUID workflow instance. Если ``None`` —
            берётся из ``exchange.properties`` / ``context.route_id``
            либо генерируется deterministically через ``uuid5``.
        run_id: Опц. execution run id. Если ``None`` — ``"default"``.
        name: Опц. имя процессора.

    Behavior:
        * Загружает или создаёт ``WorkflowState`` в БД.
        * Возобновляет выполнение с ``step_index + 1``.
        * После каждого успешного шага — checkpoint (upsert).
        * При ошибке — сохраняет ``compensating_actions``, переводит state
          в ``"compensating"``, выполняет компенсации, затем
          ``"rolled_back"`` (или остаётся ``"compensating"`` при failure
          компенсации).
        * При успехе — state ``"completed"``.
        * Если БД недоступна на старте — fallback к in-memory поведению
          (как :class:`SagaProcessor`).
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.SIDE_EFFECTING
    compensatable: ClassVar[bool] = True

    def __init__(
        self,
        steps: list[SagaStep],
        *,
        workflow_id: str | None = None,
        run_id: str | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"saga_lra({len(steps)} steps)")
        self._steps = steps
        self._workflow_id = workflow_id
        self._run_id = run_id

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        wf_id_str = (
            self._workflow_id
            or exchange.get_property("saga_workflow_id")
            or exchange.get_property("workflow_id")
            or context.route_id
            or "saga"
        )
        run_id = self._run_id or exchange.get_property("saga_run_id") or "default"

        try:
            workflow_id = uuid.UUID(str(wf_id_str))
        except ValueError:
            workflow_id = uuid.uuid5(uuid.NAMESPACE_DNS, str(wf_id_str))

        repo = await self._get_repo()
        state_record = None
        if repo is not None:
            try:
                state_record = await repo.load(workflow_id, run_id)
                if state_record is None:
                    state_record = await repo.save(
                        workflow_id=workflow_id,
                        run_id=run_id,
                        step_index=-1,
                        state="running",
                    )
            except Exception as exc:
                _lra_logger.warning(
                    "SagaLRA '%s' DB load/create failed (%s), falling back to in-memory",
                    self.name,
                    exc,
                )
                repo = None

        if repo is None:
            return await self._run_in_memory(exchange, context)

        start_idx = state_record.step_index + 1

        for i in range(start_idx, len(self._steps)):
            step = self._steps[i]
            try:
                await step.forward.process(exchange, context)

                if exchange.status == ExchangeStatus.failed:
                    raise RuntimeError(exchange.error or f"Step {i} failed")

                try:
                    await repo.save(
                        workflow_id=workflow_id,
                        run_id=run_id,
                        step_index=i,
                        state="running",
                    )
                except Exception as db_exc:
                    _lra_logger.warning(
                        "SagaLRA checkpoint save failed at step %d (continuing): %s",
                        i,
                        db_exc,
                    )
            except Exception as exc:
                _lra_logger.error("SagaLRA step %d failed: %s. Compensating...", i, exc)
                exchange.set_property("saga_failed_step", i)
                exchange.set_property("saga_error", str(exc))

                comp_actions: list[dict[str, Any]] = [
                    {
                        "step_index": idx,
                        "forward_name": self._steps[idx].forward.name,
                        "compensate_name": (
                            self._steps[idx].compensate.name
                            if self._steps[idx].compensate
                            else None
                        ),
                    }
                    for idx in range(i)
                    if self._steps[idx].compensate is not None
                ]

                try:
                    await repo.save(
                        workflow_id=workflow_id,
                        run_id=run_id,
                        step_index=i,
                        compensating_actions=comp_actions,
                        state="compensating",
                        error_message=str(exc),
                    )
                except Exception as db_exc:
                    _lra_logger.error("Failed to save compensating state: %s", db_exc)

                any_failed = False
                for comp_step in reversed(self._steps[:i]):
                    if comp_step.compensate is not None:
                        try:
                            exchange.status = ExchangeStatus.processing
                            exchange.error = None
                            await comp_step.compensate.process(exchange, context)
                        except Exception as comp_exc:
                            any_failed = True
                            _lra_logger.error(
                                "SagaLRA compensation failed: %s", comp_exc
                            )

                final_state = "compensating" if any_failed else "rolled_back"
                try:
                    await repo.save(
                        workflow_id=workflow_id,
                        run_id=run_id,
                        step_index=i,
                        state=final_state,
                        error_message=str(exc) if any_failed else None,
                    )
                except Exception as db_exc:
                    _lra_logger.error("Failed to save final saga state: %s", db_exc)

                exchange.fail(f"Saga failed at step {i}: {exc}")
                return None

        try:
            await repo.save(
                workflow_id=workflow_id,
                run_id=run_id,
                step_index=len(self._steps) - 1,
                state="completed",
            )
        except Exception as db_exc:
            _lra_logger.error("Failed to save completed saga state: %s", db_exc)

        exchange.set_property("saga_completed", True)
        return None

    async def _get_repo(self) -> Any | None:
        """Lazy-load DB deps and return a ``_RepoProxy`` or ``None``."""
        try:
            sm = _lazy_get_smart_session_manager()()
            from src.backend.infrastructure.workflow.saga_state import (
                WorkflowStateRepository,
            )
        except Exception:
            return None
        return _RepoProxy(sm, WorkflowStateRepository)

    async def _run_in_memory(
        self, exchange: Exchange[Any], context: ExecutionContext
    ) -> None:
        """Fallback in-memory saga (same logic as :class:`SagaProcessor`)."""
        completed_steps: list[SagaStep] = []
        saga_workflow_id = (
            self._workflow_id
            or exchange.get_property("saga_workflow_id")
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
                _lra_logger.error("Saga step %d failed: %s. Compensating...", i, exc)
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
                            _lra_logger.error("Saga compensation failed: %s", comp_exc)
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
        """Сериализует SagaLRA-шаги в YAML-spec.

        Каждый шаг сериализуется как ``{forward: {...}, compensate: {...}}``;
        если хоть один step не сериализуется (callable forward/compensate)
        — возвращается ``None`` для всего SagaLRA.
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
        return {
            "saga_lra": {
                "steps": steps_spec,
                "workflow_id": self._workflow_id,
                "run_id": self._run_id,
            }
        }
