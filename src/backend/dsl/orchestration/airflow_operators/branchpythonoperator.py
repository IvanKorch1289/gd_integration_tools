from __future__ import annotations
import asyncio
import threading
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

class BranchPythonOperator(BaseProcessor):
    """Python callable возвращает имя следующей task/branch.

    Apache Airflow BranchPythonOperator: https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/operators.html#branchpythonoperator

    Args:
        python_callable: Callable, возвращающий ``str`` (task_id для follow-up)
            или :data:`BRANCH_SKIP_VALUE` если downstream нужно skip.
        allowed_branches: optional whitelist — если callable вернёт имя не из
            списка — error (для safety, default None = no restriction).
        name: имя процессора.

    Side effect: ``exchange.set_property(BRANCH_DECISION_PROPERTY, branch_name)``.
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(
        self,
        python_callable: BranchResolver,
        *,
        allowed_branches: list[str] | None = None,
        name: str | None = None,
    ) -> None:
        if python_callable is None:
            raise ValueError("BranchPythonOperator: python_callable is required")
        super().__init__(name=name or "branch_python")
        self._callable = python_callable
        self._allowed = allowed_branches

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        decision = self._callable(exchange)
        if asyncio.iscoroutine(decision):
            decision = await decision
        decision_str = str(decision)

        if self._allowed is not None and decision_str not in self._allowed:
            raise ValueError(
                f"BranchPythonOperator: returned {decision_str!r}, "
                f"not in allowed_branches={self._allowed}"
            )

        exchange.set_property(BRANCH_DECISION_PROPERTY, decision_str)
        _log.debug("BranchPythonOperator: decision=%s", decision_str)

    def to_spec(self) -> dict[str, Any] | None:
        return {"type": "branch_python", "allowed_branches": self._allowed}
