"""DEPRECATED shim — use ``src.backend.core.domain.models.files`` directly.

S106 W3 (D5 B2c) перенёс files.py в ``core/domain/models/``. Этот shim —
back-compat re-export с ``DeprecationWarning`` (hard delete планируется
S106 W5 closure). OrderFile secondary association перенесён вместе
с files.

References:
- ADR-0188 (D5 plan)
- ``docs/migration/d5-models-to-core.md``
"""
from __future__ import annotations

import warnings

from src.backend.core.domain.models.files import *  # noqa: F401,F403

warnings.warn(
    "Importing from src.backend.infrastructure.database.models.files is "
    "deprecated; use src.backend.core.domain.models.files instead. "
    "This shim will be removed in S106 W5.",
    DeprecationWarning,
    stacklevel=2,
)
