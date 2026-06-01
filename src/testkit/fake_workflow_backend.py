"""Re-export of :class:`FakeWorkflowBackend <src.backend.core.workflow.fake_backend.FakeWorkflowBackend>`.

K5 S19 W3 (S-L10-1). This module re-exports the in-memory
:class:`WorkflowBackend <src.backend.core.workflow.backend.WorkflowBackend>`
implementation from the core package for convenient access via
``src.testkit.FakeWorkflowBackend``.

See the original implementation for full documentation:

* :class:`FakeWorkflowBackend <src.backend.core.workflow.fake_backend.FakeWorkflowBackend>`
* :class:`WorkflowBackend <src.backend.core.workflow.backend.WorkflowBackend>`
* :class:`WorkflowHandle <src.backend.core.workflow.backend.WorkflowHandle>`
* :class:`WorkflowResult <src.backend.core.workflow.backend.WorkflowResult>`
"""

from __future__ import annotations

from src.backend.core.workflow import (
    FakeWorkflowBackend as _Impl,
    WorkflowBackend,
    WorkflowHandle,
    WorkflowResult,
)

# Re-export under the testkit namespace with the same class reference.
# This avoids breaking existing code that imports FakeWorkflowBackend from
# src.backend.core.workflow directly while providing a convenient
# ``src.testkit.FakeWorkflowBackend`` import path.
FakeWorkflowBackend = _Impl

__all__ = ("FakeWorkflowBackend", "WorkflowBackend", "WorkflowHandle", "WorkflowResult")
