from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

_log = get_logger(__name__)

# Property name для branch decision (consumed by BranchSelector / routing logic).
BRANCH_DECISION_PROPERTY = "branch.decision"
# Sentinel: operator решил "skip downstream" (no follow-up tasks).
BRANCH_SKIP_VALUE = "__skip__"

# Type alias: branch resolver returns task/branch name (or BRANCH_SKIP_VALUE).
BranchResolver = Callable[[Exchange[Any]], str | Awaitable[str]]
Predicate = Callable[[Exchange[Any]], bool | Awaitable[bool]]

# ── BranchPythonOperator ─────────────────────────────────────────────


class BranchSelector:
    """Утилита для downstream-процессоров: получить branch decision.

    Использование::

        selector = BranchSelector(operator=branch_op)
        next_branch = selector.resolve(exchange)  # str | None
        if next_branch == BRANCH_SKIP_VALUE:
            return  # skip downstream
        # else: route к next_branch
    """

    __slots__ = ("_operator",)

    def __init__(self, operator: BaseProcessor | None = None) -> None:
        self._operator = operator

    def resolve(self, exchange: Exchange[Any]) -> str | None:
        """Возвращает branch decision или None если не установлен."""
        decision = exchange.get_property(BRANCH_DECISION_PROPERTY)
        return str(decision) if decision is not None else None

    def is_skip(self, exchange: Exchange[Any]) -> bool:
        return self.resolve(exchange) == BRANCH_SKIP_VALUE
