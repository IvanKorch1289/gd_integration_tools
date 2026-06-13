"""DEPRECATED shim — use ``src.backend.core.domain.models.base`` directly.

S106 W1 (D5 B1) перенёс base.py в ``core/domain/models/``. Этот shim —
back-compat re-export с ``DeprecationWarning`` (1 sprint grace, hard delete
S106 W5). Pattern аналогичен S95 W4 AuthGateway + S103 W3 ``core/audit/facade.py``.

References:
- ADR-0188
- ``docs/migration/d5-models-to-core.md``
"""
from __future__ import annotations

import warnings

from src.backend.core.domain.models.base import *  # noqa: F401,F403

warnings.warn(
    "Importing from src.backend.infrastructure.database.models.base is "
    "deprecated; use src.backend.core.domain.models.base instead. "
    "This shim will be removed in S106 W5.",
    DeprecationWarning,
    stacklevel=2,
)
