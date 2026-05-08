"""Backward-compat shim для retry.

Sprint 1 V16 Single-Entry (Step 3.2): canonical-реализация переехала в
``src.backend.core.resilience.retry``. Этот модуль остаётся как тонкий
re-export для существующих callsite'ов; будет удалён в Step 3.3 после
миграции callsites.
"""

from __future__ import annotations

from src.backend.core.resilience.retry import (
    Retry,
    RetryBudgetExhausted,
    RetryPolicy,
    with_retry,
)

__all__ = ("Retry", "RetryBudgetExhausted", "RetryPolicy", "with_retry")
