"""Tests for src.backend.core.config.workflow.

D-AUDIT-A8-05 fix (cycle 1): ``bootstrap_defaults_enabled`` поле удалено
вместе с ``_bootstrap_default_declarations``. Тесты проверяют, что поле
больше не присутствует в ``WorkflowSettings``.
"""

from __future__ import annotations

from src.backend.core.config.workflow import WorkflowSettings


class TestWorkflowSettings:
    """D-AUDIT-A8-05 fix (cycle 1): WorkflowSettings не имеет bootstrap-полей."""

    def test_bootstrap_defaults_enabled_field_removed(self) -> None:
        """D-AUDIT-A8-05 fix: поле удалено (saga-демо больше не существуют)."""
        assert "bootstrap_defaults_enabled" not in WorkflowSettings.model_fields

    def test_workflow_settings_instantiates_empty(self) -> None:
        """Пустой WorkflowSettings создаётся без ошибок (после удаления полей)."""
        s = WorkflowSettings()
        # model_fields пустой или содержит только служебные поля yaml_group/model_config
        assert hasattr(s, "yaml_group")
        assert s.yaml_group == "workflow"
