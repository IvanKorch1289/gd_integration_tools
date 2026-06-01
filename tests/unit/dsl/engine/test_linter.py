"""Unit-тесты для DSL Linter — W003 (unused property) и E002 (unknown action).

Wave ``[wave:s6/k3-dsl-linter-lsp]``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.backend.dsl.engine.linter import DSLLinter, LintIssue
from src.backend.dsl.engine.pipeline import Pipeline
from src.backend.dsl.engine.processors.base import BaseProcessor


class _DummyProcessor(BaseProcessor):
    """Тестовый процессор-заглушка."""

    def __init__(self, name: str = "dummy") -> None:
        super().__init__(name=name)

    async def process(self, exchange: object, context: object) -> None:
        pass


class _SetPropertyProcessor(BaseProcessor):
    """Тестовый SetPropertyProcessor."""

    def __init__(self, key: str = "test_key", value: Any = None) -> None:
        super().__init__(name=f"set_property:{key}")
        self.key = key
        self.value = value

    async def process(self, exchange: object, context: object) -> None:
        pass


class _FilterProcessor(BaseProcessor):
    """Тестовый FilterProcessor с source_property."""

    def __init__(self, source_property: str = "body") -> None:
        super().__init__(name="filter_test")
        self.source_property = source_property

    async def process(self, exchange: object, context: object) -> None:
        pass


class _DispatchActionProcessor(BaseProcessor):
    """Тестовый DispatchActionProcessor."""

    def __init__(self, action: str = "test.action") -> None:
        super().__init__(name=f"dispatch:{action}")
        self.action = action

    async def process(self, exchange: object, context: object) -> None:
        pass


class _SkillInvokeProcessor(BaseProcessor):
    """Тестовый SkillInvokeProcessor."""

    def __init__(
        self,
        skill_id: str = "test.skill",
        result_property: str = "skill_result",
    ) -> None:
        super().__init__(name=f"skill_invoke:{skill_id}")
        self.skill_id = skill_id
        self.result_property = result_property

    async def process(self, exchange: object, context: object) -> None:
        pass


class _MemoryRecallProcessor(BaseProcessor):
    """Тестовый MemoryRecallProcessor."""

    def __init__(
        self,
        namespace: str = "test:ns",
        query_property: str = "body.query",
        result_property: str = "memory_recall",
    ) -> None:
        super().__init__(name=f"memory_recall:{namespace}")
        self.namespace = namespace
        self.query_property = query_property
        self.result_property = result_property

    async def process(self, exchange: object, context: object) -> None:
        pass


class _AgentRunProcessor(BaseProcessor):
    """Тестовый AgentRunProcessor."""

    def __init__(
        self,
        workflow_id: str = "test_workflow",
        result_property: str = "agent_result",
    ) -> None:
        super().__init__(name=f"agent_run:{workflow_id}")
        self.workflow_id = workflow_id
        self.result_property = result_property

    async def process(self, exchange: object, context: object) -> None:
        pass


class _MCPToolProcessor(BaseProcessor):
    """Тестовый MCPToolProcessor."""

    def __init__(
        self,
        tool_name: str = "test_tool",
        result_property: str = "mcp_result",
    ) -> None:
        super().__init__(name=f"mcp_tool:{tool_name}")
        self.tool_name = tool_name
        self.result_property = result_property

    async def process(self, exchange: object, context: object) -> None:
        pass


class _AIRpaProcessor(BaseProcessor):
    """Тестовый AIRpaProcessor."""

    def __init__(
        self,
        task: str = "click button",
        action_property: str = "ai_rpa.action",
    ) -> None:
        super().__init__(name="ai_rpa_test")
        self.task = task
        self.action_property = action_property

    async def process(self, exchange: object, context: object) -> None:
        pass


# ── W003: Unused property detection ─────────────────────────────────────────────


class TestW003UnusedProperty:
    """Тесты для W003 — неиспользуемые set_property."""

    def test_set_property_used_by_filter(self) -> None:
        """Использованное set_property не вызывает warning."""
        pipeline = Pipeline(route_id="test")
        pipeline.add_processor(_SetPropertyProcessor(key="my_data", value=42))
        pipeline.add_processor(_FilterProcessor(source_property="property:my_data"))

        issues = DSLLinter().lint(pipeline)
        w003_issues = [i for i in issues if i.code == "W003"]
        assert len(w003_issues) == 0

    def test_set_property_used_by_skill_invoke(self) -> None:
        """result_property от SkillInvokeProcessor читается."""
        pipeline = Pipeline(route_id="test")
        pipeline.add_processor(
            _SkillInvokeProcessor(skill_id="test.skill", result_property="skill_result")
        )
        pipeline.add_processor(_FilterProcessor(source_property="property:skill_result"))

        issues = DSLLinter().lint(pipeline)
        w003_issues = [i for i in issues if i.code == "W003"]
        assert len(w003_issues) == 0

    def test_set_property_used_by_memory_recall(self) -> None:
        """result_property от MemoryRecallProcessor читается."""
        pipeline = Pipeline(route_id="test")
        pipeline.add_processor(
            _MemoryRecallProcessor(
                namespace="test:ns",
                query_property="body.query",
                result_property="memory_context",
            )
        )
        pipeline.add_processor(_FilterProcessor(source_property="property:memory_context"))

        issues = DSLLinter().lint(pipeline)
        w003_issues = [i for i in issues if i.code == "W003"]
        assert len(w003_issues) == 0

    def test_set_property_used_by_agent_run(self) -> None:
        """result_property от AgentRunProcessor читается."""
        pipeline = Pipeline(route_id="test")
        pipeline.add_processor(
            _AgentRunProcessor(
                workflow_id="test_workflow", result_property="agent_result"
            )
        )
        pipeline.add_processor(_FilterProcessor(source_property="property:agent_result"))

        issues = DSLLinter().lint(pipeline)
        w003_issues = [i for i in issues if i.code == "W003"]
        assert len(w003_issues) == 0

    def test_set_property_used_by_mcp_tool(self) -> None:
        """result_property от MCPToolProcessor читается."""
        pipeline = Pipeline(route_id="test")
        pipeline.add_processor(
            _MCPToolProcessor(tool_name="test_tool", result_property="mcp_result")
        )
        pipeline.add_processor(_FilterProcessor(source_property="property:mcp_result"))

        issues = DSLLinter().lint(pipeline)
        w003_issues = [i for i in issues if i.code == "W003"]
        assert len(w003_issues) == 0

    def test_set_property_used_by_ai_rpa(self) -> None:
        """action_property от AIRpaProcessor читается."""
        pipeline = Pipeline(route_id="test")
        pipeline.add_processor(
            _AIRpaProcessor(task="click button", action_property="rpa_action")
        )
        pipeline.add_processor(_FilterProcessor(source_property="property:rpa_action"))

        issues = DSLLinter().lint(pipeline)
        w003_issues = [i for i in issues if i.code == "W003"]
        assert len(w003_issues) == 0

    def test_unused_set_property_triggers_w003(self) -> None:
        """Неиспользуемое set_property вызывает W003 warning."""
        pipeline = Pipeline(route_id="test")
        pipeline.add_processor(_SetPropertyProcessor(key="unused_data", value=42))
        # Нет процессора который читает unused_data

        issues = DSLLinter().lint(pipeline)
        w003_issues = [i for i in issues if i.code == "W003"]
        assert len(w003_issues) == 1
        assert w003_issues[0].severity == "warning"
        assert "unused_data" in w003_issues[0].message
        assert w003_issues[0].processor_index == 0

    def test_multiple_unused_properties(self) -> None:
        """Несколько неиспользуемых свойств - несколько W003."""
        pipeline = Pipeline(route_id="test")
        pipeline.add_processor(_SetPropertyProcessor(key="unused1", value=1))
        pipeline.add_processor(_SetPropertyProcessor(key="unused2", value=2))

        issues = DSLLinter().lint(pipeline)
        w003_issues = [i for i in issues if i.code == "W003"]
        assert len(w003_issues) == 2

    def test_used_in_body_reference(self) -> None:
        """Свойство используется в body.field — не вызывает warning."""
        pipeline = Pipeline(route_id="test")
        pipeline.add_processor(_SetPropertyProcessor(key="my_data", value=42))
        pipeline.add_processor(_FilterProcessor(source_property="body.field"))

        issues = DSLLinter().lint(pipeline)
        w003_issues = [i for i in issues if i.code == "W003"]
        # body.field не читает property:my_data, поэтому my_data - unused
        assert len(w003_issues) == 1


# ── E002: Unknown action detection ───────────────────────────────────────────────


class TestE002UnknownAction:
    """Тесты для E002 — неизвестные actions."""

    def test_no_issues_when_registry_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Нет issues когда action зарегистрирован."""

        class MockRegistry:
            def list_actions(self):
                return ["known.action", "another.action"]

        monkeypatch.setattr(
            "src.backend.dsl.engine.linter.action_handler_registry", MockRegistry()
        )

        pipeline = Pipeline(route_id="test")
        pipeline.add_processor(_DispatchActionProcessor(action="known.action"))

        issues = DSLLinter().lint(pipeline)
        e002_issues = [i for i in issues if i.code == "E002"]
        assert len(e002_issues) == 0

    def test_unknown_action_triggers_e002(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Неизвестный action вызывает E002 error."""

        class MockRegistry:
            def list_actions(self):
                return ["known.action", "another.action"]

        monkeypatch.setattr(
            "src.backend.dsl.engine.linter.action_handler_registry", MockRegistry()
        )

        pipeline = Pipeline(route_id="test")
        pipeline.add_processor(_DispatchActionProcessor(action="unknown.action"))

        issues = DSLLinter().lint(pipeline)
        e002_issues = [i for i in issues if i.code == "E002"]
        assert len(e002_issues) == 1
        assert e002_issues[0].severity == "error"
        assert "unknown.action" in e002_issues[0].message
        assert "known.action" in e002_issues[0].suggestion

    def test_multiple_unknown_actions(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Несколько неизвестных actions — несколько E002."""

        class MockRegistry:
            def list_actions(self):
                return ["known.action"]

        monkeypatch.setattr(
            "src.backend.dsl.engine.linter.action_handler_registry", MockRegistry()
        )

        pipeline = Pipeline(route_id="test")
        pipeline.add_processor(_DispatchActionProcessor(action="unknown1"))
        pipeline.add_processor(_DispatchActionProcessor(action="unknown2"))

        issues = DSLLinter().lint(pipeline)
        e002_issues = [i for i in issues if i.code == "E002"]
        assert len(e002_issues) == 2

    def test_registry_unavailable_skips_check(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Когда registry недоступен — E002 не вызывается (graceful degradation)."""

        def raise_import_error():
            raise ImportError("Registry not available")

        monkeypatch.setattr(
            "src.backend.dsl.engine.linter.action_handler_registry.list_actions",
            raise_import_error,
        )

        pipeline = Pipeline(route_id="test")
        pipeline.add_processor(_DispatchActionProcessor(action="any.action"))

        issues = DSLLinter().lint(pipeline)
        e002_issues = [i for i in issues if i.code == "E002"]
        assert len(e002_issues) == 0


# ── LintIssue dataclass ──────────────────────────────────────────────────────────


class TestLintIssue:
    """Тесты LintIssue dataclass."""

    def test_lint_issue_creation(self) -> None:
        """LintIssue создается с правильными полями."""
        issue = LintIssue(
            code="W003",
            severity="warning",
            message="Test message",
            processor_index=5,
        )
        assert issue.code == "W003"
        assert issue.severity == "warning"
        assert issue.message == "Test message"
        assert issue.processor_index == 5
        assert issue.suggestion == ""

    def test_lint_issue_with_suggestion(self) -> None:
        """LintIssue с suggestion."""
        issue = LintIssue(
            code="E002",
            severity="error",
            message="Unknown action",
            suggestion="Register the action first",
            processor_index=2,
        )
        assert issue.suggestion == "Register the action first"


# ── DSLLinter integration ────────────────────────────────────────────────────────


class TestDSLLinterIntegration:
    """Интеграционные тесты DSLLinter."""

    def test_empty_pipeline_e001(self) -> None:
        """Пустой pipeline вызывает E001."""
        pipeline = Pipeline(route_id="empty")

        issues = DSLLinter().lint(pipeline)
        assert any(i.code == "E001" for i in issues)

    def test_valid_pipeline_no_issues(self) -> None:
        """Валидный pipeline не вызывает issues."""
        pipeline = Pipeline(route_id="valid")
        pipeline.add_processor(_DummyProcessor("proc1"))
        pipeline.add_processor(_DummyProcessor("proc2"))

        issues = DSLLinter().lint(pipeline)
        error_issues = [i for i in issues if i.severity == "error"]
        assert len(error_issues) == 0
