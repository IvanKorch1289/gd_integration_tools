"""Backward-compat shim для OrderKindRepository (Sprint 7, R-V15-16).

Канонический модуль теперь — ``extensions.core_entities.orderkinds.repositories.orderkinds``.
Этот shim сохраняется на 1 minor-цикл и эмитит DeprecationWarning.
"""

from __future__ import annotations

import warnings

from extensions.core_entities.orderkinds.repositories.orderkinds import (
    OrderKindRepository,
    get_order_kind_repo,
)

__all__ = ("OrderKindRepository", "get_order_kind_repo")

warnings.warn(
    "src.backend.infrastructure.repositories.orderkinds устарел; используйте "
    "extensions.core_entities.orderkinds.repositories.orderkinds (R-V15-16).",
    DeprecationWarning,
    stacklevel=2,
)
