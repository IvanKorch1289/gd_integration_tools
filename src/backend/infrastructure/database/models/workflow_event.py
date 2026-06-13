"""DEPRECATED shim — use ``src.backend.core.domain.models.workflow_event`` directly.

S106 W4 (D5 B3) перенёс workflow_event.py в ``core/domain/models/``. Этот
shim — back-compat re-export с ``DeprecationWarning`` (hard delete
планируется S106 W5 closure).

Native PG Enum (WorkflowEventType) сохраняется. Cross-reference к
``workflow_instances.id`` через ForeignKey table name (string) — не
зависит от расположения модуля.

References:
- ADR-0188 (D5 plan)
- ``docs/migration/d5-models-to-core.md``
"""
from __future__ import annotations

import warnings

from src.backend.core.domain.models.workflow_event import *  # noqa: F401,F403

warnings.warn(
    "Importing from src.backend.infrastructure.database.models.workflow_event is "
    "deprecated; use src.backend.core.domain.models.workflow_event instead. "
    "This shim will be removed in S106 W5.",
    DeprecationWarning,
    stacklevel=2,
)
