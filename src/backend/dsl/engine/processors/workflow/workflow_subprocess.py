"""S171 M8 — WorkflowSubprocessProcessor.

Thin wrapper для запуска sub-workflow из текущего workflow.
Запускает child workflow через orchestrator engine.

Pattern (Ponytail, D167): thin wrapper, no abstractions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

# Module-level imports (callable through module reference) so tests can patch
# ``src.backend.infrastructure.workflow.factory.create_workflow_backend``
# and have it propagate to ``run_workflow_by_id``.
from src.backend.core.logging import get_logger
from src.backend.core.workflow.backend import WorkflowBackend as _WorkflowBackend
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import (
    processor,  # B-1 fix (cycle 1): registry integration
)
from src.backend.infrastructure.workflow import factory as _wf_factory

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

_logger = get_logger("dsl.workflow.subprocess")

__all__ = ("WorkflowSubprocessProcessor", "run_workflow_by_id")


async def run_workflow_by_id(
    workflow_id: str, *, input_data: dict[str, Any], timeout: float = 60.0
) -> dict[str, Any]:
    """Запустить workflow по его ID (sub-workflow entry point).

    Thin wrapper над orchestrator. Используется из WorkflowSubprocessProcessor
    и может вызываться напрямую из кода.

    P1-W2 fix (audit 2026-08-18): реально стартует child workflow через
    :func:`create_workflow_backend` + :meth:`WorkflowBackend.start_child_workflow`
    вместо stub возвращающего ``{"status": "started"}``.

    Args:
        workflow_id: ID workflow из registry.
        input_data: Входные данные для workflow.
        timeout: Таймаут в секундах.

    Returns:
        Результат child workflow (dict) или error-маркер.

    """
    from datetime import timedelta

    from src.backend.core.di.app_state import get_app_ref
    from src.backend.dsl.workflow.launcher import WorkflowLauncher

    launcher = WorkflowLauncher(installed_workflows={workflow_id: "1.0.0"})
    resolved = launcher.resolve(workflow_id, ">=1.0,<2.0")
    _logger.info("subworkflow run id=%s resolved=%s", workflow_id, resolved)

    # Resolve parent handle (если внутри workflow context) и backend.
    # Если parent handle нет (e.g. dev_light standalone) — используем
    # default backend без parent linkage.
    app = get_app_ref()
    backend: _WorkflowBackend | None = None
    parent_handle: object | None = None
    if app is not None:
        backend = getattr(app.state, "workflow_backend", None)
        parent_handle = getattr(app.state, "current_workflow_handle", None)

    if backend is None:
        # Lazy-create default backend (dev_light / tests / standalone).
        try:
            backend = await _wf_factory.create_workflow_backend(
                kind="auto",
                profile=getattr(app.state, "profile", None) if app else None,
            )
        except Exception as exc:  # pragma: no cover
            _logger.warning(
                "subworkflow backend init failed: %s — falling back to fake", exc
            )
            try:
                backend = await _wf_factory.create_workflow_backend(kind="fake")
            except Exception as fb_exc:  # pragma: no cover
                _logger.error("subworkflow fake backend init also failed: %s", fb_exc)
                return {
                    "workflow_id": workflow_id,
                    "resolved_version": resolved,
                    "input": input_data,
                    "status": "failed",
                    "error": f"backend init failed: {fb_exc}",
                }

    # Реальный старт child workflow.
    # Уникальный child workflow_id: parent_id + child_name + uuid.
    import uuid

    child_wf_id = f"{workflow_id}-sub-{uuid.uuid4().hex[:8]}"
    # namespace — default (override через app.state.workflow_namespace если задан).
    namespace = (
        getattr(app.state, "workflow_namespace", "default") if app else "default"
    )
    task_queue = (
        getattr(app.state, "workflow_task_queue", "default") if app else "default"
    )
    try:
        if parent_handle is not None:
            handle = await backend.start_child_workflow(
                parent_handle=parent_handle,
                workflow_name=workflow_id,
                workflow_id=child_wf_id,
                input=input_data,
                task_queue=task_queue,
                execution_timeout=timedelta(seconds=timeout),
            )
        else:
            # Standalone: стартуем без parent linkage.
            handle = await backend.start_workflow(
                workflow_name=workflow_id,
                workflow_id=child_wf_id,
                input=input_data,
                namespace=namespace,
                task_queue=task_queue,
                execution_timeout=timedelta(seconds=timeout),
            )
        _logger.info(
            "subworkflow started child_id=%s handle=%s",
            child_wf_id,
            getattr(handle, "workflow_id", "?"),
        )
        return {
            "workflow_id": workflow_id,
            "child_workflow_id": child_wf_id,
            "resolved_version": resolved,
            "input": input_data,
            "status": "started",
            "handle_workflow_id": getattr(handle, "workflow_id", child_wf_id),
        }
    except Exception as exc:
        _logger.error("subworkflow start failed id=%s: %s", workflow_id, exc)
        return {
            "workflow_id": workflow_id,
            "resolved_version": resolved,
            "input": input_data,
            "status": "failed",
            "error": str(exc),
        }


# cycle-5/D-AUDIT-505 — register 4 workflow processors via @processor() decorator
@processor(
    "workflow_subprocess",
    namespace="core",
    capabilities=("workflow.subprocess.invoke",),
    spec_schema={
        "type": "object",
        "properties": {
            "workflow_id": {"type": "string"},
            "input_from": {"type": "string"},
            "to": {"type": "string"},
            "timeout": {"type": "number", "exclusiveMinimum": 0},
        },
        "required": ["workflow_id"],
    },
    meta={"tier": 1, "category": "workflow"},
)
class WorkflowSubprocessProcessor(BaseProcessor):
    """Запускает sub-workflow по его ID.

    Args:
        workflow_id: ID child workflow для запуска.
        input_from: Путь к входным данным в exchange (default ``"body"``).
        to: Куда записать результат (default ``"body.subprocess_result"``).
        timeout: Таймаут в секундах (default 60).

    """

    required_capability: ClassVar[str | None] = "workflow.subprocess.invoke"
    audit_event: str | None = "workflow.subprocess.invoked"

    def __init__(
        self,
        *,
        workflow_id: str,
        input_from: str = "body",
        to: str = "body.subprocess_result",
        timeout: float = 60.0,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"workflow_subprocess:{workflow_id}")
        self.workflow_id = workflow_id
        self.input_from = input_from
        self.target = to
        self.timeout = timeout

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Метод process (см. signature)."""
        if not await self.auth_check(exchange, action="invoke"):
            return
        # Resolve input from dotted path
        head, _, rest = self.input_from.partition(".")
        if head == "body":
            cursor: Any = exchange.in_message.body
            for part in rest.split(".") if rest else []:
                cursor = cursor.get(part) if isinstance(cursor, dict) else None
            input_data = cursor if cursor is not None else {}
        else:
            input_data = exchange.in_message.body

        _logger.info(
            "workflow_subprocess invoke id=%s timeout=%.1fs",
            self.workflow_id,
            self.timeout,
        )
        result = await run_workflow_by_id(
            self.workflow_id, input_data=input_data, timeout=self.timeout
        )
        self.set_result(exchange, self.target, result)
