"""ADR-0395 — YAML-декларации регистрируются как ``WorkflowDescriptor``.

Дефект (2, critical): ``workflow_setup._register_workflow_declarations_from_filesystem``
клала в реестр descriptor'ов **декларацию** (``WorkflowDeclaration``), а не
``WorkflowDescriptor``. Admin-trigger читал ``descriptor.input_schema``
(AttributeError), MCP-экспорт читал ``descriptor.tags`` (AttributeError,
проглоченный try/except → тихая потеря MCP-tool'а).

Проверяем:
* в реестре лежит ``WorkflowDescriptor`` с ожидаемыми полями;
* ``input_schema`` / ``tags`` доступны (admin-trigger и MCP-контракты);
* дескрипторы перезаписываются при повторной регистрации (hot-reload).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.backend.dsl.workflow.spec import WorkflowDeclaration
from src.backend.infrastructure.workflow.registry import (
    WorkflowDescriptor,
    workflow_registry,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def _clean_descriptor_registry() -> Any:
    """Изолировать descriptor-реестр на время теста."""
    snapshot = {
        name: workflow_registry.get(name)
        for name in [d.name for d in workflow_registry.list_all()]
    }
    route_ids = {
        name: workflow_registry.get_route_id(name)
        for name in [d.name for d in workflow_registry.list_all()]
    }
    try:
        yield workflow_registry
    finally:
        workflow_registry.clear()
        for name, descriptor in snapshot.items():
            if descriptor is not None:
                workflow_registry.register(descriptor, route_id=route_ids[name] or name)


def _load_credit_workflow() -> WorkflowDeclaration:
    """Загрузить YAML-декларацию расширения credit_pipeline."""
    from src.backend.dsl.workflow.yaml_io import load_workflow_from_file

    return load_workflow_from_file(
        _REPO_ROOT
        / "extensions"
        / "credit_pipeline"
        / "workflows"
        / "credit_assessment.workflow.yaml"
    )


class TestDescriptorRegistration:
    """Регистрация YAML-декларации как descriptor'а."""

    def test_registered_entry_is_workflow_descriptor(
        self, _clean_descriptor_registry: Any
    ) -> None:
        """В реестре — ``WorkflowDescriptor``, а не ``WorkflowDeclaration``."""
        from src.backend.plugins.composition.workflow_setup import _register_descriptor

        decl = _load_credit_workflow()
        _register_descriptor(decl, route_id="routes/credit_pipeline/credit_assessment")

        descriptor = workflow_registry.get("credit_assessment")
        assert isinstance(descriptor, WorkflowDescriptor)
        assert not isinstance(descriptor, WorkflowDeclaration)

    def test_descriptor_exposes_admin_and_mcp_fields(
        self, _clean_descriptor_registry: Any
    ) -> None:
        """``input_schema`` / ``tags`` доступны — admin-trigger и MCP не падают."""
        from src.backend.plugins.composition.workflow_setup import _register_descriptor

        decl = _load_credit_workflow()
        _register_descriptor(decl, route_id="routes/credit_pipeline/credit_assessment")

        descriptor = workflow_registry.get("credit_assessment")
        assert descriptor is not None
        # admin-trigger: descriptor.input_schema.model_validate(...)
        assert descriptor.input_schema is None
        # MCP: descriptor.tags → join
        assert descriptor.tags == ()
        assert isinstance(descriptor.description, str)
        assert descriptor.max_attempts >= 1

    def test_route_id_binding_is_preserved(
        self, _clean_descriptor_registry: Any
    ) -> None:
        """``route_id`` сохраняется — admin-trigger идёт по нему в store."""
        from src.backend.plugins.composition.workflow_setup import _register_descriptor

        decl = _load_credit_workflow()
        _register_descriptor(decl, route_id="routes/credit_pipeline/credit_assessment")

        assert (
            workflow_registry.get_route_id("credit_assessment")
            == "routes/credit_pipeline/credit_assessment"
        )

    def test_reregistration_replaces_descriptor(
        self, _clean_descriptor_registry: Any
    ) -> None:
        """Повторная регистрация заменяет descriptor (hot-reload), не падает."""
        from src.backend.plugins.composition.workflow_setup import _register_descriptor

        decl = _load_credit_workflow()
        _register_descriptor(decl, route_id="routes/credit_pipeline/credit_assessment")
        _register_descriptor(decl, route_id="routes/credit_pipeline/credit_assessment")

        descriptor = workflow_registry.get("credit_assessment")
        assert descriptor is not None
        assert workflow_registry.get_route_id("credit_assessment") == (
            "routes/credit_pipeline/credit_assessment"
        )

    def test_filesystem_registration_stores_descriptor(
        self,
        _clean_descriptor_registry: Any,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Auto-load из EXTENSIONS_DIR кладёт в реестр descriptor (не декларацию)."""
        from src.backend.plugins.composition import workflow_setup

        workflow_dir = tmp_path / "demo_plugin" / "workflows"
        workflow_dir.mkdir(parents=True)
        (workflow_dir / "demo_flow.workflow.yaml").write_text(
            "name: demo_flow\n"
            "description: Demo workflow\n"
            "tags: [demo]\n"
            "steps:\n"
            "  - type: call_function\n"
            "    ref: tests.unit.infrastructure.workflow.test_workflow_declaration_bridge:_sample_target\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("EXTENSIONS_DIR", str(tmp_path))

        # Сброс кеша загруженных деклараций (module-level state).
        monkeypatch.setattr(workflow_setup, "_declarations_loaded", False)
        monkeypatch.setattr(workflow_setup, "_loaded_declarations", [])

        registered = workflow_setup._register_workflow_declarations_from_filesystem()

        assert registered == 1
        descriptor = workflow_registry.get("demo_flow")
        assert isinstance(descriptor, WorkflowDescriptor)
        assert descriptor.description == "Demo workflow"
        assert descriptor.tags == ("demo",)
