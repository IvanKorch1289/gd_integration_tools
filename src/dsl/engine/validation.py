"""Pipeline validation — pre-execution checks for DSL pipelines."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

__all__ = ("PipelineValidator", "ValidationResult")

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ValidationIssue:
    level: str  # "error", "warning", "info"
    message: str
    processor_index: int | None = None
    processor_name: str | None = None


@dataclass(slots=True)
class ValidationResult:
    valid: bool
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.level == "warning"]


class PipelineValidator:
    """Валидатор DSL pipeline перед выполнением.

    Проверяет:
    - Наличие процессоров
    - Порядок зависимых процессоров (PII → LLM → Restore)
    - Наличие обработки ошибок
    - Циклические ссылки между маршрутами
    """

    def validate(self, pipeline: Any) -> ValidationResult:
        issues: list[ValidationIssue] = []

        if not pipeline.processors:
            issues.append(ValidationIssue("error", "Pipeline has no processors"))
            return ValidationResult(valid=False, issues=issues)

        proc_names = [
            getattr(p, "name", p.__class__.__name__)
            for p in pipeline.processors
        ]
        proc_types = [p.__class__.__name__ for p in pipeline.processors]

        self._check_ordering(proc_types, proc_names, issues)
        self._check_error_handling(proc_types, issues)
        self._check_route_refs(pipeline, issues)

        has_errors = any(i.level == "error" for i in issues)
        return ValidationResult(valid=not has_errors, issues=issues)

    def _check_ordering(
        self,
        proc_types: list[str],
        proc_names: list[str],
        issues: list[ValidationIssue],
    ) -> None:
        sanitize_idx = None
        restore_idx = None
        llm_idx = None

        for i, ptype in enumerate(proc_types):
            if ptype == "SanitizePIIProcessor":
                sanitize_idx = i
            elif ptype == "RestorePIIProcessor":
                restore_idx = i
            elif ptype == "LLMCallProcessor":
                llm_idx = i

        if restore_idx is not None and sanitize_idx is None:
            issues.append(ValidationIssue(
                "error", "RestorePIIProcessor without preceding SanitizePIIProcessor",
                processor_index=restore_idx,
            ))

        if sanitize_idx is not None and restore_idx is not None:
            if restore_idx < sanitize_idx:
                issues.append(ValidationIssue(
                    "error",
                    "RestorePIIProcessor must come after SanitizePIIProcessor",
                    processor_index=restore_idx,
                ))

        if llm_idx is not None and sanitize_idx is not None:
            if llm_idx < sanitize_idx:
                issues.append(ValidationIssue(
                    "warning",
                    "LLMCallProcessor before SanitizePIIProcessor — PII may leak to LLM",
                    processor_index=llm_idx,
                ))

        prompt_idx = None
        for i, ptype in enumerate(proc_types):
            if ptype == "PromptComposerProcessor":
                prompt_idx = i

        if llm_idx is not None and prompt_idx is not None:
            if llm_idx < prompt_idx:
                issues.append(ValidationIssue(
                    "warning",
                    "LLMCallProcessor before PromptComposerProcessor — prompt may not be composed",
                    processor_index=llm_idx,
                ))

    def _check_error_handling(
        self,
        proc_types: list[str],
        issues: list[ValidationIssue],
    ) -> None:
        has_try_catch = "TryCatchProcessor" in proc_types
        has_retry = "RetryProcessor" in proc_types
        has_dead_letter = "DeadLetterProcessor" in proc_types
        has_fallback = "FallbackChainProcessor" in proc_types
        has_external = any(
            t in proc_types
            for t in ("DispatchActionProcessor", "LLMCallProcessor", "MCPToolProcessor")
        )

        if has_external and not (has_try_catch or has_retry or has_dead_letter or has_fallback):
            issues.append(ValidationIssue(
                "warning",
                "Pipeline calls external services but has no error handling "
                "(TryCatch, Retry, DeadLetter, or Fallback)",
            ))

    def _check_route_refs(
        self, pipeline: Any, issues: list[ValidationIssue]
    ) -> None:
        for i, proc in enumerate(pipeline.processors):
            ptype = proc.__class__.__name__
            if ptype == "PipelineRefProcessor":
                target = getattr(proc, "_target_route_id", None)
                if target == pipeline.route_id:
                    issues.append(ValidationIssue(
                        "error",
                        f"Circular reference: route '{pipeline.route_id}' references itself",
                        processor_index=i,
                    ))


pipeline_validator = PipelineValidator()
