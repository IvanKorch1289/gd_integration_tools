from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
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


class ShortCircuitOperator(BaseProcessor):
    """Skip downstream tasks если predicate returns ``False``.

    Apache Airflow ShortCircuitOperator: https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/operators.html#shortcircuitoperator

    Args:
        predicate: Callable → bool. False = skip (write ``BRANCH_SKIP_VALUE``
            в property + ``exchange.skip_downstream()``).
        ignore_downstream_trigger_rules: если True — skip applies даже
            если downstream tasks имеют ``trigger_rule=always``. Default False.
        name: имя процессора.
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(
        self,
        predicate: Predicate,
        *,
        ignore_downstream_trigger_rules: bool = False,
        name: str | None = None,
    ) -> None:
        if predicate is None:
            raise ValueError("ShortCircuitOperator: predicate is required")
        super().__init__(name=name or "short_circuit")
        self._predicate = predicate
        self._ignore_trigger_rules = ignore_downstream_trigger_rules

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        result = self._predicate(exchange)
        if asyncio.iscoroutine(result):
            result = await result

        if result:
            _log.debug("ShortCircuitOperator: predicate=True, continue")
            # No decision property set — engine treats as "proceed normally"
            return

        _log.debug("ShortCircuitOperator: predicate=False, skip downstream")
        exchange.set_property(BRANCH_DECISION_PROPERTY, BRANCH_SKIP_VALUE)
        if self._ignore_trigger_rules:
            exchange.set_property("short_circuit.force_skip", True)
        exchange.stop()  # short-circuit: stop further processing in current route

    def to_spec(self) -> dict[str, Any] | None:
        return {
            "type": "short_circuit",
            "ignore_downstream_trigger_rules": self._ignore_trigger_rules,
        }
