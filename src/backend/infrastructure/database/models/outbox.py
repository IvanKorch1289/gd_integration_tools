"""DEPRECATED shim — use ``src.backend.core.domain.models.outbox`` directly.

S106 W1 (D5 B1) перенёс outbox.py в ``core/domain/models/``. Этот shim —
back-compat re-export с ``DeprecationWarning`` (1 sprint grace, hard delete
S106 W5).

References:
- ADR-0188
- ``docs/migration/d5-models-to-core.md``
"""
from __future__ import annotations

import warnings

from src.backend.core.domain.models.outbox import *  # noqa: F401,F403

warnings.warn(
    "Importing from src.backend.infrastructure.database.models.outbox is "
    "deprecated; use src.backend.core.domain.models.outbox instead. "
    "This shim will be removed in S106 W5.",
    DeprecationWarning,
    stacklevel=2,
)
