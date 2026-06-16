"""S103 W2 — ``CronScheduleProcessor`` (DSL skeleton).

Temporal-style scheduled workflow. Регистрирует cron-расписание,
при срабатывании запускает ``workflow_name`` с ``workflow_args``.

S103 W2 scope: DSL skeleton + constructor + canonical DSL method
``RouteBuilder.cron_schedule(...)``. Real Temporal Schedule-to-Close
wiring (apscheduler adapter + Temporal Schedule client) — S103+ W3+
(multi-wave scope, требует dedicated sprint).

S103 W2 = "facade pattern": DSL method exists, real backend = future sprint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CronScheduleProcessor:
    """DSL processor: register cron schedule для workflow.

    Attributes:
        name: Имя schedule (idempotency key).
        cron_expr: 5-field cron expression.
        workflow_name: Имя workflow для запуска при срабатывании.
        workflow_args: Аргументы workflow (default ``None``).
        namespace: Workflow namespace (Temporal).
        task_queue: Workflow task queue.
        result_property: Куда писать handle в DSL message.
        timezone: Timezone для cron evaluation.
        metadata: Доп. metadata для audit log.
    """

    name: str
    cron_expr: str
    workflow_name: str
    workflow_args: dict[str, Any] | None = None
    namespace: str = "default"
    task_queue: str = "default"
    result_property: str = "schedule_handle"
    timezone: str = "UTC"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Валидация параметров."""
        if not self.name:
            raise ValueError("name обязателен (idempotency key)")
        if not self.cron_expr or len(self.cron_expr.split()) != 5:
            raise ValueError(
                f"cron_expr должен быть 5-field выражением, "
                f"получено: {self.cron_expr!r}"
            )
        if not self.workflow_name:
            raise ValueError("workflow_name обязателен")

    @property
    def kind(self) -> str:
        """Kind для runtime dispatch (``cron_schedule``)."""
        return "cron_schedule"

    def to_dict(self) -> dict[str, Any]:
        """Сериализация для audit / spec dump."""
        return {
            "kind": self.kind,
            "name": self.name,
            "cron_expr": self.cron_expr,
            "workflow_name": self.workflow_name,
            "workflow_args": self.workflow_args,
            "namespace": self.namespace,
            "task_queue": self.task_queue,
            "result_property": self.result_property,
            "timezone": self.timezone,
            "metadata": self.metadata,
        }
