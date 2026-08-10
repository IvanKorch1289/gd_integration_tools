"""Smoke-тесты Sprint 4 К3-B §5 — workflow_setup runtime.

D-AUDIT-A8-05 fix (cycle 1): ``_bootstrap_default_declarations`` удалена.
Ранее тесты проверяли saga-bootstrap, но saga-демо удалены в 9164a59.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.backend.plugins.composition import workflow_setup


@pytest.fixture
def _clean_registry() -> workflow_setup.WorkflowCompilerRegistry:
    """Свежий compiler-реестр, чтобы тесты не загрязняли друг друга."""

    registry = workflow_setup.workflow_compiler_registry
    snapshot = registry.snapshot()
    registry.clear()
    try:
        yield registry
    finally:
        registry.clear()
        registry.restore(snapshot)


class TestBootstrapRemoved:
    """D-AUDIT-A8-05 fix (cycle 1): _bootstrap_default_declarations удалена."""

    def test_bootstrap_function_removed(self) -> None:
        """D-AUDIT-A8-05 fix: функция удалена — saga-демо модулей больше нет."""
        assert not hasattr(workflow_setup, "_bootstrap_default_declarations"), (
            "workflow_setup._bootstrap_default_declarations должна быть удалена "
            "(saga-демо удалены в коммите 9164a59)"
        )

    def test_settings_workflow_attribute_removed(self) -> None:
        """D-AUDIT-A8-05 fix: settings.workflow.bootstrap_defaults_enabled удалён.

        Поле осиротело после удаления bootstrap-функции — оставлено бы для
        silent fail-OPEN в external tooling. Удалено полностью.
        """
        # Проверяем, что поле удалено из WorkflowSettings (для legacy-compat cleanup).
        from src.backend.core.config.workflow import WorkflowSettings

        assert "bootstrap_defaults_enabled" not in WorkflowSettings.model_fields, (
            "WorkflowSettings.bootstrap_defaults_enabled должен быть удалён "
            "(D-AUDIT-A8-05 fix cycle 1)"
        )

    @pytest.mark.asyncio
    async def test_start_runtime_no_crash_without_bootstrap(
        self, _clean_registry: workflow_setup.WorkflowCompilerRegistry,
    ) -> None:
        """D-AUDIT-A8-05 fix: ``start_workflow_runtime`` отрабатывает без bootstrap."""
        app = SimpleNamespace(state=SimpleNamespace())
        await workflow_setup.start_workflow_runtime(app)
        assert app.state.workflow_compiler_registry is workflow_setup.workflow_compiler_registry


@pytest.mark.asyncio
async def test_start_workflow_runtime_attaches_registry_to_app_state(
    _clean_registry: workflow_setup.WorkflowCompilerRegistry,
) -> None:
    """``start_workflow_runtime`` кладёт compiler-реестр в ``app.state``."""

    app = SimpleNamespace(state=SimpleNamespace())
    await workflow_setup.start_workflow_runtime(app)

    assert app.state.workflow_compiler_registry is _clean_registry
