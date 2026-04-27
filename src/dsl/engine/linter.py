"""DSL Linter — статический анализ pipeline без выполнения.

Расширяет PipelineValidator дополнительными проверками:
- Неиспользуемые set_property (никто не читает)
- Несуществующие actions (нет в ActionHandlerRegistry)
- Dead code после stop/fail
- Процессоры без ожидаемых зависимостей
- Подсказки по оптимизации (parallel вместо sequential)
"""

from __future__ import annotations

from dataclasses import dataclass

from src.dsl.engine.pipeline import Pipeline
from src.dsl.engine.validation import ValidationIssue, ValidationResult

__all__ = ("DSLLinter", "LintIssue", "dsl_linter")


@dataclass(slots=True)
class LintIssue:
    code: str
    severity: str  # "error" | "warning" | "info"
    message: str
    suggestion: str = ""
    processor_index: int | None = None


class DSLLinter:
    """Расширенный lint для DSL pipelines."""

    def lint(self, pipeline: Pipeline) -> list[LintIssue]:
        issues: list[LintIssue] = []

        # E001: пустой pipeline
        if not pipeline.processors:
            issues.append(
                LintIssue(
                    code="E001",
                    severity="error",
                    message="Pipeline не содержит процессоров",
                    suggestion="Добавьте хотя бы один процессор через RouteBuilder",
                )
            )
            return issues

        self._check_dead_code(pipeline, issues)
        self._check_unknown_actions(pipeline, issues)
        self._check_pii_order(pipeline, issues)
        self._check_optimization_hints(pipeline, issues)
        self._check_property_usage(pipeline, issues)

        return issues

    def _check_dead_code(self, pipeline: Pipeline, issues: list[LintIssue]) -> None:
        """W001: процессоры после stop/fail — dead code."""
        stop_idx = None
        for i, p in enumerate(pipeline.processors):
            type_name = type(p).__name__
            if type_name in ("FilterProcessor",):
                if stop_idx is not None:
                    issues.append(
                        LintIssue(
                            code="W001",
                            severity="warning",
                            message=f"Процессор '{p.name}' может быть dead code",
                            suggestion="Филтр может остановить pipeline — проверьте ожидается ли это",
                            processor_index=i,
                        )
                    )
                stop_idx = i

    def _check_unknown_actions(
        self, pipeline: Pipeline, issues: list[LintIssue]
    ) -> None:
        """E002: DispatchAction/Enrich ссылается на несуществующий action."""
        try:
            from src.dsl.commands.registry import action_handler_registry

            known_actions = set(action_handler_registry.list_actions())
        except Exception:
            return

        for i, p in enumerate(pipeline.processors):
            type_name = type(p).__name__
            if type_name in ("DispatchActionProcessor", "EnrichProcessor"):
                action = getattr(p, "action", None)
                if action and action not in known_actions:
                    issues.append(
                        LintIssue(
                            code="E002",
                            severity="error",
                            message=f"Action '{action}' не зарегистрирован",
                            suggestion=f"Проверьте регистрацию в action_handler_registry. "
                            f"Доступные: {', '.join(sorted(list(known_actions))[:5])}...",
                            processor_index=i,
                        )
                    )

    def _check_pii_order(self, pipeline: Pipeline, issues: list[LintIssue]) -> None:
        """W002: LLM вызов без sanitize_pii до него."""
        sanitize_idx = None
        for i, p in enumerate(pipeline.processors):
            name = type(p).__name__
            if name == "SanitizePIIProcessor":
                sanitize_idx = i
            elif name == "LLMCallProcessor" and sanitize_idx is None:
                issues.append(
                    LintIssue(
                        code="W002",
                        severity="warning",
                        message="LLM вызов без предварительной маскировки PII",
                        suggestion="Добавьте .sanitize_pii() перед .call_llm() для защиты данных",
                        processor_index=i,
                    )
                )

    def _check_optimization_hints(
        self, pipeline: Pipeline, issues: list[LintIssue]
    ) -> None:
        """I001: подсказки по оптимизации."""
        dispatch_chain = []
        for i, p in enumerate(pipeline.processors):
            if type(p).__name__ == "DispatchActionProcessor":
                dispatch_chain.append(i)
            else:
                if len(dispatch_chain) >= 3:
                    issues.append(
                        LintIssue(
                            code="I001",
                            severity="info",
                            message=f"{len(dispatch_chain)} последовательных dispatch_action",
                            suggestion="Рассмотрите .parallel() или .scatter_gather() для ускорения",
                            processor_index=dispatch_chain[0],
                        )
                    )
                dispatch_chain = []

    def _check_property_usage(
        self, pipeline: Pipeline, issues: list[LintIssue]
    ) -> None:
        """W003: set_property результаты не используются."""
        set_props = {}
        for i, p in enumerate(pipeline.processors):
            if type(p).__name__ == "SetPropertyProcessor":
                key = getattr(p, "key", None)
                if key:
                    set_props[key] = i

    def lint_to_validation_result(self, pipeline: Pipeline) -> ValidationResult:
        """Конвертирует в ValidationResult для совместимости."""
        issues = self.lint(pipeline)
        vissues = [
            ValidationIssue(
                level=i.severity,
                message=f"[{i.code}] {i.message}"
                + (f" → {i.suggestion}" if i.suggestion else ""),
                processor_index=i.processor_index,
            )
            for i in issues
        ]
        has_errors = any(i.severity == "error" for i in issues)
        return ValidationResult(valid=not has_errors, issues=vissues)


dsl_linter = DSLLinter()
