"""Tests for core.workflow public API."""

from __future__ import annotations

from src.backend.core.workflow import (
    FakeWorkflowBackend,
    WorkflowBackend,
    WorkflowHandle,
    WorkflowResult,
    WorkflowStatus,
)


class TestWorkflowPublicApi:
    def test_re_exports(self) -> None:
        assert WorkflowBackend is not None
        assert WorkflowHandle is not None
        assert WorkflowResult is not None
        assert WorkflowStatus is not None
        assert FakeWorkflowBackend is not None
