"""ADR-0395 — перекомпиляция workflow'а заменяет класс в реестре.

Дефект (4, high): ``emitter.compile_workflow`` глотал ``ValueError`` от
``workflow_registry.register`` (только DEBUG-лог). В реестре оставался
прежний класс: worker/replay видели старую версию, а post-check
``compile_workflows`` (проверка только по имени) проходил.

Проверяем:
* после recompile в реестре лежит **новый** класс;
* post-check ``compile_workflows`` ловит устаревший класс;
* ``WorkflowRegistry.unregister`` удаляет класс по имени.
"""

from __future__ import annotations

import pytest

pytest.importorskip(
    "temporalio", reason="temporalio not installed — run: uv sync --extra workflow"
)

from src.backend.core.workflow_registry import WorkflowRegistry
from src.backend.dsl.workflow.compiler.emitter import (
    compile_workflow,
    compile_workflows,
)
from src.backend.dsl.workflow.spec import ActivityDeclaration, WorkflowDeclaration


def _decl(name: str, *, step_name: str) -> WorkflowDeclaration:
    """Декларация workflow'а с одним activity-шагом."""
    return WorkflowDeclaration(name=name, steps=[ActivityDeclaration(name=step_name)])


@pytest.fixture
def _clean_workflow_registry() -> WorkflowRegistry:
    """Изолировать реестр Temporal workflow-классов.

    Берём объект реестра **из модуля emitter'а** — он владеет тем же
    singleton'ом, в который идёт регистрация при компиляции. Прямой
    импорт из ``core.workflow_registry`` может указать на другой объект:
    в suite'е есть тест, делающий ``importlib.reload`` этого модуля
    (singleton пересоздаётся), и ссылки расходятся.
    """
    from src.backend.dsl.workflow.compiler.emitter import workflow_registry

    snapshot = dict(workflow_registry._classes)
    workflow_registry.clear()
    try:
        yield workflow_registry
    finally:
        workflow_registry.clear()
        workflow_registry._classes.update(snapshot)


class TestRecompileReplacesClass:
    """Перекомпиляция с тем же именем."""

    def test_recompile_replaces_registered_class(
        self, _clean_workflow_registry: WorkflowRegistry
    ) -> None:
        """В реестре после recompile — новый класс, а не прежний."""
        first = compile_workflow(_decl("orders.flow", step_name="orders.create"))
        second = compile_workflow(_decl("orders.flow", step_name="orders.create_v2"))

        registered = _clean_workflow_registry.get("orders.flow")
        assert registered is not None
        assert registered is second.cls
        assert registered is not first.cls

    def test_compile_workflows_post_check_detects_stale_class(
        self,
        _clean_workflow_registry: WorkflowRegistry,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Post-check ловит ситуацию «в реестре лежит устаревший класс»."""
        from src.backend.dsl.workflow.compiler import emitter as emitter_module

        compiled = compile_workflow(
            _decl("orders.postcheck", step_name="orders.create")
        )

        class _StaleRegistry:
            """Реестр, который молча не регистрирует новый класс."""

            def register(self, cls: type) -> type:  # noqa: D102
                return cls

            def unregister(self, name: str) -> bool:  # noqa: D102
                return False

            def get(self, name: str) -> type | None:  # noqa: D102
                return compiled.cls

        monkeypatch.setattr(emitter_module, "workflow_registry", _StaleRegistry())

        with pytest.raises(RuntimeError, match="устаревший"):
            compile_workflows([_decl("orders.postcheck", step_name="orders.create")])

    def test_compile_workflows_post_check_detects_missing_registration(
        self,
        _clean_workflow_registry: WorkflowRegistry,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Post-check ловит ситуацию «класс вообще не зарегистрирован»."""
        from src.backend.dsl.workflow.compiler import emitter as emitter_module

        class _EmptyRegistry:
            """Реестр без зарегистрированных классов."""

            def register(self, cls: type) -> type:  # noqa: D102
                return cls

            def unregister(self, name: str) -> bool:  # noqa: D102
                return False

            def get(self, name: str) -> type | None:  # noqa: D102
                return None

        monkeypatch.setattr(emitter_module, "workflow_registry", _EmptyRegistry())

        with pytest.raises(RuntimeError, match="NOT registered"):
            compile_workflows([_decl("orders.missing", step_name="orders.create")])


class TestWorkflowRegistryUnregister:
    """``WorkflowRegistry.unregister`` — удаление класса по имени."""

    def test_unregister_removes_class(
        self, _clean_workflow_registry: WorkflowRegistry
    ) -> None:
        """После unregister имя больше не резолвится."""
        compiled = compile_workflow(
            _decl("orders.unregister", step_name="orders.create")
        )
        assert "orders.unregister" in _clean_workflow_registry

        removed = _clean_workflow_registry.unregister("orders.unregister")

        assert removed is True
        assert "orders.unregister" not in _clean_workflow_registry
        assert _clean_workflow_registry.unregister("orders.unregister") is False
        del compiled
