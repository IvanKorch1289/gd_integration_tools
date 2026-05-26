"""FakeWorkflowBackend — re-export of in-memory WorkflowBackend implementation.

Этот модуль — re-export :class:`FakeWorkflowBackend` из
:mod:`src.backend.core.workflow.fake_backend` для удобного доступа
через ``src.testkit`` public API.

См. оригинальный модуль для документации.

Этот модуль — часть ``src/testkit/`` public API (K5 S19 W3).
"""

from __future__ import annotations

from src.backend.core.workflow.fake_backend import FakeWorkflowBackend

__all__ = ("FakeWorkflowBackend",)
