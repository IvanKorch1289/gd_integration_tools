"""CompensateWorkflow API (S171 M10 P0, D173).

Saga-pattern compensation для multi-step workflows.
Temporal не имеет native compensation (в отличие от Cadence/Camunda),
поэтому реализуем через signal + saga_state.

Контракт:
1. Worker посылает signal ``_compensation_request`` workflow
2. Workflow handler получает список compensation_steps + reason
3. Workflow выполняет compensation в обратном порядке
4. Каждый step помечается в saga_state как compensated

Pattern (Ponytail, D173): Pydantic model + signal name const.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ("COMPENSATE_SIGNAL", "CompensateWorkflowRequest")


# Stable signal name — Temporal signal contract.
# Workers должны слушать это имя для compensation.
COMPENSATE_SIGNAL: str = "_compensation_request"


class CompensateWorkflowRequest(BaseModel):
    """Запрос на compensation workflow.

    Attributes:
        workflow_id: ID workflow для compensation.
        compensation_steps: Имена шагов для compensate (в обратном порядке).
        reason: Причина compensation (для логирования).
        metadata: Дополнительные данные (compensation context).
    """

    workflow_id: str
    compensation_steps: list[str] = Field(default_factory=list)
    reason: str
    metadata: dict[str, str] = Field(default_factory=dict)
