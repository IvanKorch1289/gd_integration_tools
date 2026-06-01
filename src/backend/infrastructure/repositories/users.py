"""Backward-compat shim для UserRepository (Sprint 7, R-V15-16).

Канонический модуль теперь — ``extensions.core_entities.users.repositories.users``
(см. R-V15-16: миграция CRUD-ресурсов из ядра в extensions/). Этот shim
сохраняется на 1 minor-цикл и эмитит DeprecationWarning.
"""

from __future__ import annotations

import warnings

from extensions.core_entities.users.repositories.users import (
    UserRepository,
    get_user_repo,
)

__all__ = ("UserRepository", "get_user_repo")

warnings.warn(
    "src.backend.infrastructure.repositories.users устарел; используйте "
    "extensions.core_entities.users.repositories.users (R-V15-16).",
    DeprecationWarning,
    stacklevel=2,
)
