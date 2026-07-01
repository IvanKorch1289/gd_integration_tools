from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

_log = get_logger(__name__)

# Property name для branch decision (consumed by BranchSelector / routing logic).
BRANCH_DECISION_PROPERTY = "branch.decision"
# Sentinel: operator решил "skip downstream" (no follow-up tasks).
BRANCH_SKIP_VALUE = "__skip__"

# Type alias: branch resolver returns task/branch name (or BRANCH_SKIP_VALUE).
BranchResolver = Callable[[Exchange[Any]], str | Awaitable[str]]
Predicate = Callable[[Exchange[Any]], bool | Awaitable[bool]]

# ── BranchPythonOperator ─────────────────────────────────────────────


class BranchDateTimeOperator(BaseProcessor):
    """Branch на основе date/time condition.

    Apache Airflow BranchDateTimeOperator: https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/operators.html#branchdatetimeoperator

    Args:
        target_task_if_true: branch name если текущее время в target window.
        target_task_if_false: branch name если НЕ в window.
        target_lower: datetime — начало окна (inclusive). None = no lower bound.
        target_upper: datetime — конец окна (inclusive). None = no upper bound.
        use_task_execution_date: использовать ``execution_date`` из exchange
            headers (default True). Иначе ``datetime.now(UTC)``.
        name: имя процессора.
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(  # noqa: PLR0913
        self,
        target_task_if_true: str,
        target_task_if_false: str,
        *,
        target_lower: datetime | None = None,
        target_upper: datetime | None = None,
        use_task_execution_date: bool = True,
        name: str | None = None,
    ) -> None:
        if target_lower is not None and target_upper is not None:
            if target_lower > target_upper:
                raise ValueError("BranchDateTimeOperator: target_lower > target_upper")
        super().__init__(name=name or "branch_datetime")
        self._true_branch = target_task_if_true
        self._false_branch = target_task_if_false
        self._lower = target_lower
        self._upper = target_upper
        self._use_execution_date = use_task_execution_date

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Выбирает ветку по попаданию текущего времени в заданный интервал."""
        if self._use_execution_date:
            exec_date = exchange.in_message.get_header("execution_date")
            if isinstance(exec_date, datetime):
                now = exec_date
            else:
                now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        else:
            now = datetime.now(tz=timezone.utc).replace(tzinfo=None)

        in_window = True
        if self._lower is not None and now < self._lower:
            in_window = False
        if self._upper is not None and now > self._upper:
            in_window = False

        decision = self._true_branch if in_window else self._false_branch
        exchange.set_property(BRANCH_DECISION_PROPERTY, decision)
        _log.debug(
            "BranchDateTimeOperator: now=%s in_window=%s → %s",
            now.isoformat(),
            in_window,
            decision,
        )

    def to_spec(self) -> dict[str, Any] | None:
        return {
            "type": "branch_datetime",
            "true_branch": self._true_branch,
            "false_branch": self._false_branch,
            "lower": self._lower.isoformat() if self._lower else None,
            "upper": self._upper.isoformat() if self._upper else None,
        }
