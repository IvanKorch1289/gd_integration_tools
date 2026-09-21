"""Tests for src.backend.dsl.engine.validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from src.backend.dsl.engine.validation import (
    PipelineValidator,
    ValidationIssue,
    ValidationResult,
    pipeline_validator,
)


@dataclass
class FakeProcessor:
    name: str
    _target_route_id: str | None = None


@dataclass
class FakePipeline:
    route_id: str
    processors: list[Any]


@pytest.mark.unit
class TestValidationIssue:
    def test_basic_issue(self) -> None:
        issue = ValidationIssue("error", "something broke")
        assert issue.level == "error"
        assert issue.message == "something broke"
        assert issue.processor_index is None

    def test_issue_with_processor(self) -> None:
        issue = ValidationIssue(
            "warning", "slow", processor_index=2, processor_name="p2"
        )
        assert issue.processor_index == 2
        assert issue.processor_name == "p2"


@pytest.mark.unit
class TestValidationResult:
    def test_empty_result_is_valid(self) -> None:
        result = ValidationResult(valid=True)
        assert result.valid is True
        assert result.issues == []
        assert result.errors == []
        assert result.warnings == []

    def test_errors_property_filters(self) -> None:
        result = ValidationResult(
            valid=False,
            issues=[
                ValidationIssue("error", "err1"),
                ValidationIssue("warning", "warn1"),
                ValidationIssue("info", "info1"),
            ],
        )
        assert len(result.errors) == 1
        assert len(result.warnings) == 1
        assert len(result.issues) == 3


@pytest.mark.unit
class TestPipelineValidator:
    def test_empty_pipeline(self) -> None:
        pipeline = FakePipeline("r1", [])
        result = PipelineValidator().validate(pipeline)
        assert result.valid is False
        assert any("no processors" in i.message.lower() for i in result.issues)

    def test_valid_single_processor(self) -> None:
        pipeline = FakePipeline("r1", [FakeProcessor("p1")])
        result = PipelineValidator().validate(pipeline)
        assert result.valid is True

    def test_restore_without_sanitize(self) -> None:
        pipeline = FakePipeline("r1", [FakeProcessor("restore", _target_route_id=None)])
        # Use a processor whose class name triggers the check
        pipeline.processors[0].__class__.__name__ = "RestorePIIProcessor"
        result = PipelineValidator().validate(pipeline)
        assert any(
            "without preceding SanitizePIIProcessor" in i.message for i in result.issues
        )

    def test_restore_before_sanitize(self) -> None:
        pipeline = FakePipeline("r1", [])

        # We need to simulate class names; use a dummy object with overridden __class__
        class RestorePIIProcessor:
            pass

        class SanitizePIIProcessor:
            pass

        pipeline.processors = [RestorePIIProcessor(), SanitizePIIProcessor()]
        result = PipelineValidator().validate(pipeline)
        assert any("must come after" in i.message for i in result.issues)

    def test_sanitize_before_restore_valid(self) -> None:
        pipeline = FakePipeline("r1", [])

        class SanitizePIIProcessor:
            pass

        class RestorePIIProcessor:
            pass

        pipeline.processors = [SanitizePIIProcessor(), RestorePIIProcessor()]
        result = PipelineValidator().validate(pipeline)
        assert not any("RestorePIIProcessor" in i.message for i in result.errors)

    def test_llm_before_sanitize_warning(self) -> None:
        pipeline = FakePipeline("r1", [])

        class LLMCallProcessor:
            pass

        class SanitizePIIProcessor:
            pass

        pipeline.processors = [LLMCallProcessor(), SanitizePIIProcessor()]
        result = PipelineValidator().validate(pipeline)
        assert any("PII may leak" in i.message for i in result.issues)

    def test_llm_after_prompt_warning(self) -> None:
        pipeline = FakePipeline("r1", [])

        class LLMCallProcessor:
            pass

        class PromptComposerProcessor:
            pass

        pipeline.processors = [LLMCallProcessor(), PromptComposerProcessor()]
        result = PipelineValidator().validate(pipeline)
        assert any("prompt may not be composed" in i.message for i in result.issues)

    def test_external_without_error_handling_warning(self) -> None:
        pipeline = FakePipeline("r1", [])

        class DispatchActionProcessor:
            pass

        pipeline.processors = [DispatchActionProcessor()]
        result = PipelineValidator().validate(pipeline)
        assert any("no error handling" in i.message for i in result.issues)

    def test_external_with_try_catch_ok(self) -> None:
        pipeline = FakePipeline("r1", [])

        class DispatchActionProcessor:
            pass

        class TryCatchProcessor:
            pass

        pipeline.processors = [DispatchActionProcessor(), TryCatchProcessor()]
        result = PipelineValidator().validate(pipeline)
        assert not any("no error handling" in i.message for i in result.issues)

    def test_external_with_retry_ok(self) -> None:
        pipeline = FakePipeline("r1", [])

        class LLMCallProcessor:
            pass

        class RetryProcessor:
            pass

        pipeline.processors = [LLMCallProcessor(), RetryProcessor()]
        result = PipelineValidator().validate(pipeline)
        assert not any("no error handling" in i.message for i in result.issues)

    def test_circular_reference_detected(self) -> None:
        pipeline = FakePipeline("self_route", [])

        class PipelineRefProcessor:
            _target_route_id = "self_route"

        pipeline.processors = [PipelineRefProcessor()]
        result = PipelineValidator().validate(pipeline)
        assert any("Circular reference" in i.message for i in result.issues)

    def test_no_circular_reference(self) -> None:
        pipeline = FakePipeline("route_a", [])

        class PipelineRefProcessor:
            _target_route_id = "route_b"

        pipeline.processors = [PipelineRefProcessor()]
        result = PipelineValidator().validate(pipeline)
        assert not any("Circular reference" in i.message for i in result.issues)

    def test_singleton_exists(self) -> None:
        assert isinstance(pipeline_validator, PipelineValidator)
