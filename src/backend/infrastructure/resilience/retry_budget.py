"""Backward-compat shim для retry budget.

Sprint 1 V16 Single-Entry (Step 3.2): canonical-реализация переехала в
``src.backend.core.resilience.retry_budget``. Этот модуль остаётся как
тонкий re-export для существующих callsite'ов; будет удалён в Step 3.3
после миграции callsites.

Объединение бывшего ``infrastructure``-варианта (per-resource, с
``record_attempt``) и ``core``-варианта (глобальный, с ``record_request``)
выполнено через alias ``record_attempt = record_request`` в новом
``RetryBudget``.
"""

from __future__ import annotations

from src.backend.core.resilience.retry_budget import (
    RetryBudget,
    RetryBudgetExhausted,
    get_retry_budget,
)

__all__ = ("RetryBudget", "RetryBudgetExhausted", "get_retry_budget")
