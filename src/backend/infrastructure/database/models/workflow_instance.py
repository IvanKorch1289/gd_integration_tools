"""DEPRECATED shim — use ``src.backend.core.domain.models.workflow_instance`` directly.

S106 W4 (D5 B3) перенёс workflow_instance.py в ``core/domain/models/``.
Этот shim — back-compat re-export с ``DeprecationWarning`` (hard delete
планируется S106 W5 closure).

Native PG Enum (WorkflowStatus) сохраняется — Alembic migration
``c3d4e5f6a7b8_workflow_tables.py`` создаёт тип независимо от расположения
модуля.

References:
- ADR-0188 (D5 plan)
- ``docs/migration/d5-models-to-core.md``
"""
from __future__ import annotations

import warnings

from src.backend.core.domain.models.workflow_instance import *  # noqa: F401,F403

warnings.warn(
    "Importing from src.backend.infrastructure.database.models.workflow_instance "
    "is deprecated; use src.backend.core.domain.models.workflow_instance instead. "
    "This shim will be removed in S106 W5.",
    DeprecationWarning,
    stacklevel=2,
)
