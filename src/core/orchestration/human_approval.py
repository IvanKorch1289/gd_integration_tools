"""R2.2 — `HumanApproval` primitive.

Workflow-pause до approval/reject от человека через signal.
Реализация — Temporal `wait_condition()` на signal-handler'е,
durable до signal или timeout.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

__all__ = ("ApprovalDecision", "ApprovalRequest", "HumanApproval")


class ApprovalRequest(BaseModel):
    """Запрос на одобрение."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: str = Field(min_length=1)
    title: str
    description: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    requested_by: str = ""
    timeout: timedelta | None = None
    approvers: tuple[str, ...] = ()
    """Список user-id, имеющих право одобрить (пустой = любой)."""


class ApprovalDecision(BaseModel):
    """Решение по запросу."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: str
    outcome: Literal["approved", "rejected", "timed_out"]
    decided_by: str = ""
    decided_at: datetime | None = None
    comment: str = ""


@runtime_checkable
class HumanApproval(Protocol):
    """Контракт human-approval primitive."""

    async def request(
        self, *, operation_id: str, request: ApprovalRequest, namespace: str = "default"
    ) -> ApprovalDecision:
        """Зарегистрировать запрос и ждать decision.

        Backend (Temporal) подвешивает workflow до получения signal'а
        ``"approve"`` / ``"reject"`` либо timeout'а из ``request.timeout``.
        """
        ...
