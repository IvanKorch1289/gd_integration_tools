"""WorkflowContinueAsNewProcessor.

S171 M9 final: имплементация Temporal best practice "Continue-As-New".

Используется для предотвращения роста Event History в долгоживущих workflow.
Рекомендация Temporal: не превышать несколько тысяч событий в одном Execution.
Continue-As-New пересоздаёт Execution с чистой историей, передавая состояние.

Refs:
    https://docs.temporal.io/best-practices/worker#manage-event-history-growth
    https://docs.temporal.io/workflow-execution/continue-as-new

Pattern (Ponytail, D169): тонкий wrapper, без абстракций.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import (
    processor,  # B-1 fix (cycle 1): registry integration
)

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

_logger = get_logger("dsl.workflow.continue_as_new")


# cycle-5/D-AUDIT-505 — register 4 workflow processors via @processor() decorator
@processor(
    "workflow_continue_as_new",
    namespace="core",
    capabilities=("workflow.continue_as_new.request",),
    spec_schema={
        "type": "object",
        "properties": {
            "same_workflow_id": {"type": "boolean"},
            "same_input": {"type": "boolean"},
            "search_attributes": {"type": "object"},
        },
    },
    meta={"tier": 1, "category": "workflow"},
)
class WorkflowContinueAsNewProcessor(BaseProcessor):
    """Маркирует запрос на Continue-As-New в Exchange.

    Temporal worker прочитает маркер и выполнит continue_as_new.
    В DSL это используется как checkpoint в долгоживущем workflow.

    Args:
        same_workflow_id: Сохранить тот же workflow_id (по умолчанию True).
        same_input: Сохранить тот же input (по умолчанию False).
        search_attributes: Атрибуты для поиска (по умолчанию None).

    """

    required_capability: ClassVar[str | None] = "workflow.continue_as_new.request"
    audit_event: str | None = "workflow.continue_as_new.requested"

    def __init__(
        self,
        *,
        same_workflow_id: bool = True,
        same_input: bool = False,
        search_attributes: dict[str, Any] | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "workflow_continue_as_new")
        self.same_workflow_id = same_workflow_id
        self.same_input = same_input
        self.search_attributes = search_attributes or {}

    async def process(
        self, exchange: Exchange[Any], context: ExecutionContext,
    ) -> None:
        """Метод process (см. signature)."""
        if not await self.auth_check(exchange, action="request"):
            return
        marker = {
            "requested": True,
            "same_workflow_id": self.same_workflow_id,
            "same_input": self.same_input,
            "search_attributes": self.search_attributes,
            "body_snapshot": exchange.in_message.body,
        }
        _logger.info(
            "workflow_continue_as_new requested same_wf_id=%s",
            self.same_workflow_id,
        )
        self.set_result(exchange, "continue_as_new_requested", marker)
