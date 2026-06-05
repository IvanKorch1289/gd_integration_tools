"""Tests for core.workflow public API."""

from __future__ import annotations

import importlib

import pytest

import src.backend.core.workflow as workflow_module


@pytest.mark.unit
class TestWorkflowPublicApi:
    def test_re_exports(self) -> None:
        mod = importlib.reload(workflow_module)
        assert mod.WorkflowBackend is not None
        assert mod.WorkflowHandle is not None
        assert mod.WorkflowResult is not None
        assert mod.WorkflowStatus is not None
        assert mod.FakeWorkflowBackend is not None

    def test_all_exports(self) -> None:
        mod = importlib.reload(workflow_module)
        assert set(mod.__all__) == {
            "FakeWorkflowBackend",
            "WorkflowBackend",
            "WorkflowHandle",
            "WorkflowResult",
            "WorkflowStatus",
        }
