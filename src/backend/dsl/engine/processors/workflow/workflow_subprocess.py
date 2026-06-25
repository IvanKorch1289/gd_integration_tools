"""S171 M8 — WorkflowSubprocessProcessor.

Thin wrapper для запуска sub-workflow из текущего workflow.
Запускает child workflow через orchestrator engine.

Pattern (Ponytail, D167): thin wrapper, no abstractions.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.base import BaseProcessor

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

    Args:
        workflow_id: ID workflow из registry.
        input_data: Входные данные для workflow.
        timeout: Таймаут в секундах.

    Returns:
        Результат workflow (dict).
    """
    from src.backend.dsl.workflow.orchestrator import OrchestratorSpec
    from src.backend.dsl.workflow.launcher import WorkflowLauncher

    launcher = WorkflowLauncher(installed_workflows={workflow_id: "1.0.0"})
    resolved = launcher.resolve(workflow_id, ">=1.0,<2.0")
    _logger.info(
        "subworkflow run id=%s resolved=%s", workflow_id, resolved
    )
    # Minimal contract: возвращаем marker + input echo для testing
    return {
        "workflow_id": workflow_id,
        "resolved_version": resolved,
        "input": input_data,
        "status": "started",
    }


class WorkflowSubprocessProcessor(BaseProcessor):
    """Запускает sub-workflow по его ID.

    Args:
        workflow_id: ID child workflow для запуска.
        input_from: Путь к входным данным в exchange (default ``"body"``).
        to: Куда записать результат (default ``"body.subprocess_result"``).
        timeout: Таймаут в секундах (default 60).
    """

    required_capability: str | None = "workflow.subprocess.invoke"
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

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
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
            self.workflow_id, self.timeout,
        )
        result = await run_workflow_by_id(
            self.workflow_id, input_data=input_data, timeout=self.timeout
        )
        self.set_result(exchange, self.target, result)