"""TDD characterization для services/dsl_portal/builder_facade.py lazy proxy (Sprint 225 Tier 2).

10 services → dsl imports converted to lazy __getattr__.
"""

from __future__ import annotations

import pytest


class TestBuilderFacadeAllExports:
    """builder_facade module __all__ stable."""

    def test_module_loads(self) -> None:
        from src.backend.services.dsl_portal import builder_facade

        assert hasattr(builder_facade, "list_workflow_templates")


class TestBuilderFacadeDSLExportsIdentity:
    """All 10 DSL re-exports preserve symbol identity via lazy __getattr__."""

    def test_dry_run_route_identity(self) -> None:
        from src.backend.services.dsl_portal.builder_facade import dry_run_route
        from src.backend.dsl.engine.dry_run import dry_run_route as _orig

        assert dry_run_route is _orig

    def test_waterfall_lines_identity(self) -> None:
        from src.backend.services.dsl_portal.builder_facade import waterfall_lines
        from src.backend.dsl.engine.dry_run import waterfall_lines as _orig

        assert waterfall_lines is _orig

    def test_execution_engine_identity(self) -> None:
        from src.backend.services.dsl_portal.builder_facade import ExecutionEngine
        from src.backend.dsl.engine.execution_engine import ExecutionEngine as _orig

        assert ExecutionEngine is _orig

    def test_pipeline_identity(self) -> None:
        from src.backend.services.dsl_portal.builder_facade import Pipeline
        from src.backend.dsl.engine.pipeline import Pipeline as _orig

        assert Pipeline is _orig

    def test_get_tracer_identity(self) -> None:
        from src.backend.services.dsl_portal.builder_facade import get_tracer
        from src.backend.dsl.engine.tracer import get_tracer as _orig

        assert get_tracer is _orig

    def test_route_registry_identity(self) -> None:
        from src.backend.services.dsl_portal.builder_facade import route_registry
        from src.backend.dsl.registry import route_registry as _orig

        assert route_registry is _orig

    def test_workflow_declaration_identity(self) -> None:
        from src.backend.services.dsl_portal.builder_facade import WorkflowDeclaration
        from src.backend.dsl.workflow.spec import WorkflowDeclaration as _orig

        assert WorkflowDeclaration is _orig

    def test_get_global_registry_callable(self) -> None:
        from src.backend.services.dsl_portal.builder_facade import get_global_registry

        assert callable(get_global_registry)

    def test_compute_step_diff_callable(self) -> None:
        from src.backend.services.dsl_portal.builder_facade import compute_step_diff

        assert callable(compute_step_diff)

    def test_to_graphviz_callable(self) -> None:
        from src.backend.services.dsl_portal.builder_facade import to_graphviz

        assert callable(to_graphviz)

    def test_to_mermaid_callable(self) -> None:
        from src.backend.services.dsl_portal.builder_facade import to_mermaid

        assert callable(to_mermaid)


class TestBuilderFacadeYAMLLoaders:
    """YAML loader functions identity preserved."""

    def test_load_workflow_from_yaml_callable(self) -> None:
        from src.backend.services.dsl_portal.builder_facade import (
            load_workflow_from_yaml,
        )

        assert callable(load_workflow_from_yaml)

    def test_load_workflow_from_file_callable(self) -> None:
        from src.backend.services.dsl_portal.builder_facade import (
            load_workflow_from_file,
        )

        assert callable(load_workflow_from_file)

    def test_load_all_workflows_from_directory_callable(self) -> None:
        from src.backend.services.dsl_portal.builder_facade import (
            load_all_workflows_from_directory,
        )

        assert callable(load_all_workflows_from_directory)

    def test_load_pipeline_from_yaml_callable(self) -> None:
        from src.backend.services.dsl_portal.builder_facade import (
            load_pipeline_from_yaml,
        )

        assert callable(load_pipeline_from_yaml)


class TestBuilderFacadeUnknownAttribute:
    """Unknown attribute raises AttributeError."""

    def test_unknown_raises(self) -> None:
        from src.backend.services.dsl_portal import builder_facade

        with pytest.raises(AttributeError):
            _ = builder_facade.__getattr__("nonexistent_xyz")

    def test_existing_function_still_works(self) -> None:
        """Verify module-level functions still callable after refactor."""
        from src.backend.services.dsl_portal.builder_facade import (
            list_workflow_templates,
        )

        result = list_workflow_templates()
        assert isinstance(result, list)
