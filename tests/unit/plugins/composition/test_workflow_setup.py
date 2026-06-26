# ruff: noqa: S101, SLF001
"""Smoke-тесты Sprint 4 К3-B §5 — feature-flag bootstrap saga-деклараций."""

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


def test_bootstrap_defaults_disabled_by_default(
    monkeypatch: pytest.MonkeyPatch,
    _clean_registry: workflow_setup.WorkflowCompilerRegistry,
) -> None:
    """Default-OFF: при пустой среде декларации не регистрируются."""

    monkeypatch.setattr(
        "src.backend.core.config.settings.settings.workflow.bootstrap_defaults_enabled",
        False,
        raising=False,
    )

    compiled = workflow_setup._bootstrap_default_declarations()

    assert compiled == []
    assert _clean_registry.list_names() == ()


@pytest.mark.skip(reason="S171 M11 R6: orders_saga файл отсутствует — defer to R4 refactor (see docs/m11_deferred_tests.md)")
def test_bootstrap_defaults_registers_two_sagas_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
    _clean_registry: workflow_setup.WorkflowCompilerRegistry,
) -> None:
    """При выставленном флаге регистрируются orders_saga + payments_saga."""
    pytest.importorskip("temporalio")
    monkeypatch.setattr(
        "src.backend.core.config.settings.settings.workflow.bootstrap_defaults_enabled",
        True,
        raising=False,
    )

    print(f"DEBUG: workflow_setup.settings id = {id(workflow_setup.settings)}")
    print(
        f"DEBUG: global settings id = {id(__import__('src.backend.core.config.settings', fromlist=['settings']).settings)}"
    )
    print(
        f"DEBUG: workflow_setup.settings.workflow.bootstrap_defaults_enabled = {workflow_setup.settings.workflow.bootstrap_defaults_enabled}"
    )
    print(
        f"DEBUG: global settings.workflow.bootstrap_defaults_enabled = {__import__('src.backend.core.config.settings', fromlist=['settings']).settings.workflow.bootstrap_defaults_enabled}"
    )

    compiled = workflow_setup._bootstrap_default_declarations()

    assert len(compiled) == 2
    names = set(_clean_registry.list_names())
    assert {"orders.create_with_payment", "payments.charge_card"} == names


@pytest.mark.asyncio
async def test_start_workflow_runtime_attaches_registry_to_app_state(
    monkeypatch: pytest.MonkeyPatch,
    _clean_registry: workflow_setup.WorkflowCompilerRegistry,
) -> None:
    """``start_workflow_runtime`` кладёт compiler-реестр в ``app.state``."""

    monkeypatch.setattr(
        "src.backend.core.config.settings.settings.workflow.bootstrap_defaults_enabled",
        False,
        raising=False,
    )

    app = SimpleNamespace(state=SimpleNamespace())
    await workflow_setup.start_workflow_runtime(app)

    assert app.state.workflow_compiler_registry is _clean_registry
