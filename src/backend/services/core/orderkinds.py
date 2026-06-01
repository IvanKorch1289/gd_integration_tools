"""Backward-compat shim для OrderKindService (Sprint 7, R-V15-16).

Канонический модуль теперь — ``extensions.core_entities.orderkinds.services.orderkinds``
(см. R-V15-16: миграция CRUD-ресурсов из ядра в extensions/). Этот shim
сохраняется на 1 minor-цикл и эмитит DeprecationWarning.
"""

from __future__ import annotations

import warnings

from extensions.core_entities.orderkinds.services.orderkinds import (
    OrderKindService,
    get_order_kind_service,
)

__all__ = ("OrderKindService", "get_order_kind_service")

warnings.warn(
    "src.backend.services.core.orderkinds устарел; используйте "
    "extensions.core_entities.orderkinds.services.orderkinds (R-V15-16).",
    DeprecationWarning,
    stacklevel=2,
)
