"""Tests for src.backend.core.config.workflow."""

from __future__ import annotations

from src.backend.core.config.workflow import WorkflowSettings


class TestWorkflowSettings:
    def test_defaults(self) -> None:
        s = WorkflowSettings()
        assert s.bootstrap_defaults_enabled is False  # default=False per code

    def test_custom(self) -> None:
        s = WorkflowSettings(bootstrap_defaults_enabled=True)
        assert s.bootstrap_defaults_enabled is True  # explicit override
