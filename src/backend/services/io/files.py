"""Backward-compat shim для FileService (Sprint 7, R-V15-16).

Канонический модуль теперь — ``extensions.core_entities.files.services.files``
(см. R-V15-16). Этот shim сохраняется на 1 minor-цикл и эмитит DeprecationWarning.
"""

from __future__ import annotations

import warnings

from extensions.core_entities.files.services.files import FileService, get_file_service

__all__ = ("FileService", "get_file_service")

warnings.warn(
    "src.backend.services.io.files устарел; используйте "
    "extensions.core_entities.files.services.files (R-V15-16).",
    DeprecationWarning,
    stacklevel=2,
)
