"""Backward-compat shim для FileRepository (Sprint 7, R-V15-16).

Канонический модуль теперь — ``extensions.core_entities.files.repositories.files``.
Этот shim сохраняется на 1 minor-цикл и эмитит DeprecationWarning.
"""

from __future__ import annotations

import warnings

from extensions.core_entities.files.repositories.files import (
    FileRepository,
    get_file_repo,
)

__all__ = ("FileRepository", "get_file_repo")

warnings.warn(
    "src.backend.infrastructure.repositories.files устарел; используйте "
    "extensions.core_entities.files.repositories.files (R-V15-16).",
    DeprecationWarning,
    stacklevel=2,
)
