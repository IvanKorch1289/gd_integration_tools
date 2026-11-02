"""Unit-тесты для CLI generate command.

Wave [wave:h1-cli-generate]
"""

from __future__ import annotations

from src.backend.dsl.cli.generate import (
    _build_processor_code,
    _build_route_template,
    _build_workflow_template,
    _get_side_effect,
    _to_toml_style,
)


class TestBuildRouteTemplate:
    def test_build_route_template_basic(self) -> None:
        template = _build_route_template("test-route", "default", "rest")

        assert "route" in template
        assert template["route"]["id"] == "test-route"
        assert template["route"]["source"]["type"] == "rest"
        assert len(template["route"]["steps"]) == 2

    def test_build_route_template_grpc(self) -> None:
        template = _build_route_template("grpc-route", "default", "grpc")

        assert template["route"]["source"]["type"] == "grpc"
        assert "grpc" in template["route"]["source"]["path"]


class TestGetSideEffect:
    def test_ai_is_side_effecting(self) -> None:
        assert _get_side_effect("ai") == "SIDE_EFFECTING"

    def test_rpa_is_side_effecting(self) -> None:
        assert _get_side_effect("rpa") == "SIDE_EFFECTING"

    def test_db_is_side_effecting(self) -> None:
        assert _get_side_effect("db") == "SIDE_EFFECTING"

    def test_generic_is_pure(self) -> None:
        assert _get_side_effect("generic") == "PURE"

    def test_unknown_is_pure(self) -> None:
        assert _get_side_effect("unknown") == "PURE"


class TestToTomlStyle:
    def test_simple_dict(self) -> None:
        data = {"key": "value", "number": 42}
        result = _to_toml_style(data)

        # Check for single quotes (Python repr format)
        assert "key = 'value'" in result or 'key = "value"' in result
        assert "number = 42" in result

    def test_nested_dict(self) -> None:
        data = {"section": {"nested_key": "nested_value"}}
        result = _to_toml_style(data)

        assert "[section]" in result
        assert "nested_key" in result


class TestBuildProcessorCode:
    def test_sync_processor_code(self) -> None:
        code = _build_processor_code("TestProcessor", "generic", is_async=False)

        assert "class TestProcessor" in code
        assert "side_effect = SideEffectKind.PURE" in code
        assert "async def process" not in code

    def test_async_processor_code(self) -> None:
        code = _build_processor_code("AsyncProcessor", "ai", is_async=True)

        assert "class AsyncProcessor" in code
        assert "side_effect = SideEffectKind.SIDE_EFFECTING" in code
        assert "async def process" in code

    def test_processor_has_docstring(self) -> None:
        code = _build_processor_code("DocProcessor", "generic", False)

        assert '"""Processor: DocProcessor' in code
        assert "Type: generic" in code


class TestBuildWorkflowTemplate:
    """ADR-0424: заготовка workflow валидна по workflow-спеке."""

    def test_workflow_with_steps(self) -> None:
        template = _build_workflow_template("test-workflow", steps=3)

        assert template["name"] == "test-workflow"
        assert len(template["steps"]) == 3
        assert template["tags"]

    def test_workflow_default_steps(self) -> None:
        template = _build_workflow_template("default-workflow", steps=5)

        assert len(template["steps"]) == 5

    def test_workflow_steps_are_call_function_placeholders(self) -> None:
        template = _build_workflow_template("placeholder-workflow", steps=2)

        for step in template["steps"]:
            assert step["type"] == "call_function"
            assert ":" in step["ref"]

    def test_workflow_is_valid_workflow_declaration(self) -> None:
        from src.backend.dsl.workflow.spec import WorkflowDeclaration

        template = _build_workflow_template("spec-workflow", steps=2)

        decl = WorkflowDeclaration.model_validate(template)
        assert decl.name == "spec-workflow"
        assert len(decl.steps) == 2


class TestGenerateRouteIntegration:
    """Integration tests for route generation."""

    def test_route_template_structure(self) -> None:
        """Verify route template has all required fields."""
        template = _build_route_template("api-route", "default", "rest")

        route = template["route"]
        assert "id" in route
        assert "description" in route
        assert "source" in route
        assert "steps" in route
        assert "sink" in route

    def test_route_source_structure(self) -> None:
        """Verify source configuration."""
        template = _build_route_template("src-test", "default", "grpc")

        source = template["route"]["source"]
        assert "type" in source
        assert "path" in source


class TestSideEffectMapping:
    """Test side effect mapping for different processor types."""

    def test_http_side_effect(self) -> None:
        assert _get_side_effect("http") == "SIDE_EFFECTING"

    def test_empty_string_side_effect(self) -> None:
        assert _get_side_effect("") == "PURE"
