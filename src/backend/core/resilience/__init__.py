"""Resilience patterns — graceful degradation, retry budget, bulkhead, self-healing.

Sprint 1 V16 Single-Entry: пакет образован из бывшего файла-модуля
``core/resilience.py``. Существующие импорты ``from src.backend.core.resilience
import X`` остаются валидными за счёт re-export'ов.

Структура:
- :mod:`degradation` — DegradationMode, DegradationManager, singleton
  ``degradation_manager``.
- :mod:`retry_budget` — RetryBudget + ``get_retry_budget``.
- :mod:`bulkhead` — Bulkhead + ``get_bulkhead``.
- :mod:`self_healer` — SelfHealer + ``get_self_healer``.

Step 3.2 (V16) добавит сюда unified ``breaker``, ``rate_limiter``, ``retry``
поверх purgatory / pyrate_limiter / tenacity.
"""

from __future__ import annotations

from src.backend.core.resilience.bulkhead import Bulkhead, get_bulkhead
from src.backend.core.resilience.degradation import (
    ComponentState,
    DegradationManager,
    DegradationMode,
    degradation_manager,
)
from src.backend.core.resilience.retry_budget import RetryBudget, get_retry_budget
from src.backend.core.resilience.self_healer import SelfHealer, get_self_healer

__all__ = (
    "Bulkhead",
    "ComponentState",
    "DegradationManager",
    "DegradationMode",
    "RetryBudget",
    "SelfHealer",
    "degradation_manager",
    "get_bulkhead",
    "get_retry_budget",
    "get_self_healer",
)
