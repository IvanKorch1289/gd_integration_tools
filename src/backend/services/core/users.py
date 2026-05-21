"""Backward-compat shim для UserService (Sprint 7, R-V15-16).

Канонический модуль теперь — ``extensions.core_entities.users.services.users``
(см. R-V15-16: миграция CRUD-ресурсов из ядра в extensions/). Этот shim
сохраняется на 1 minor-цикл и эмитит DeprecationWarning.
"""

from __future__ import annotations

import warnings

from extensions.core_entities.users.services.users import UserService, get_user_service

__all__ = ("UserService", "get_user_service")

warnings.warn(
    "src.backend.services.core.users устарел; используйте "
    "extensions.core_entities.users.services.users (R-V15-16).",
    DeprecationWarning,
    stacklevel=2,
)
