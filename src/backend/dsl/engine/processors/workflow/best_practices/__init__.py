"""Workflow best-practice processors (S171 M9).

Temporal best-practices для долгоживущих workflows:

* :class:`WorkflowClaimCheckProcessor` — большие payloads (>2MB) через
  external storage с claim-token механизмом.
* :class:`WorkflowContinueAsNewProcessor` — Continue-As-New паттерн
  для управления ростом Event History.

Refs:
    https://docs.temporal.io/best-practices
"""

from __future__ import annotations as annotations

from src.backend.dsl.engine.processors.workflow.best_practices.claim_check import (
    WorkflowClaimCheckProcessor,
)
from src.backend.dsl.engine.processors.workflow.best_practices.continue_as_new import (
    WorkflowContinueAsNewProcessor,
)

__all__ = ("WorkflowClaimCheckProcessor", "WorkflowContinueAsNewProcessor")
