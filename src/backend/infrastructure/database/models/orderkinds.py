"""DEPRECATED shim — use ``src.backend.core.domain.models.orderkinds`` directly.

S106 W3 (D5 B2a) перенёс orderkinds.py в ``core/domain/models/``. Этот
shim — back-compat re-export с ``DeprecationWarning`` (hard delete
планируется S106 W5 closure).

References:
- ADR-0188 (D5 plan)
- ``docs/migration/d5-models-to-core.md``
"""
from __future__ import annotations

import warnings

from src.backend.core.domain.models.orderkinds import *  # noqa: F401,F403

warnings.warn(
    "Importing from src.backend.infrastructure.database.models.orderkinds is "
    "deprecated; use src.backend.core.domain.models.orderkinds instead. "
    "This shim will be removed in S106 W5.",
    DeprecationWarning,
    stacklevel=2,
)
