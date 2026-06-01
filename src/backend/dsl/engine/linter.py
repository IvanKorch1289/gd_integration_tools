"""DSL Linter — статический анализ pipeline без выполнения.

Расширяет PipelineValidator дополнительными проверками:
- Неиспользуемые set_property (никто не читает)
- Несуществующие actions (нет в ActionHandlerRegistry)
- Dead code после stop/fail
- Процессоры без ожидаемых зависимостей
- Подсказки по оптимизации (parallel вместо sequential)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.backend.dsl.engine.pipeline import Pipeline
from src.backend.dsl.engine.validation import ValidationIssue, ValidationResult

__all__ = ("DSLLinter", "LintIssue", "dsl_linter")


@dataclass(slots=True)
class LintIssue:
    code: str
    severity: str  # "error" | "warning" | "info"
    message: str
    suggestion: str = ""
    processor_index: int | None = None


# Маппинг процессоров к атрибутам, которые содержат property references.
# Key = процессор, Value = dict {attribute_name: property_path_pattern}
_PROPERTY_READ_PATTERNS: dict[str, list[str]] = {
    "SetPropertyProcessor": ["key"],
    "GetPropertyProcessor": ["property"],
    "FilterProcessor": ["expression", "source_property"],
    "TransformProcessor": ["source_property", "target_property"],
    "EnrichProcessor": ["source_property"],
    "AgentBranchProcessor": ["source_property"],
    "AgentLoopProcessor": ["stop_condition_property"],
    "SkillInvokeProcessor": ["params_property", "result_property"],
    "MemoryRecallProcessor": ["query_property", "result_property"],
    "MemoryStoreProcessor": ["key_property", "value_property"],
    "AIRpaProcessor": ["action_property"],
    "GuardrailsApplyProcessor": ["source_property"],
    "PIIMaskProcessor": ["source_property", "target_property"],
    "PIIUnmaskProcessor": ["source_property", "target_property", "token_map_property"],
}


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
            from src.backend.dsl.commands.registry import action_handler_registry

            known_actions = set(action_handler_registry.list_actions())
        except Exception as _:
            # Если registry недоступен — пропускаем проверку
            return

        for i, p in enumerate(pipeline.processors):
            type_name = type(p).__name__
            if type_name in ("DispatchActionProcessor", "EnrichProcessor"):
                action = getattr(p, "action", None)
                if action and action not in known_actions:
                    available = ", ".join(sorted(list(known_actions))[:10])
                    suffix = "..." if len(known_actions) > 10 else ""
                    issues.append(
                        LintIssue(
                            code="E002",
                            severity="error",
                            message=f"Action '{action}' не зарегистрирован в action_handler_registry",
                            suggestion=f"Доступные actions: {available}{suffix}. "
                            f"Проверьте регистрацию action.",
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
        # Собираем все установленные свойства: key -> processor_index
        set_props: dict[str, int] = {}
        for i, p in enumerate(pipeline.processors):
            type_name = type(p).__name__
            if type_name == "SetPropertyProcessor":
                key = getattr(p, "key", None)
                if key:
                    set_props[key] = i
            elif type_name == "MCPToolProcessor":
                # MCPToolProcessor устанавливает result_property
                result_prop = getattr(p, "result_property", None)
                if result_prop:
                    set_props[result_prop] = i
            elif type_name == "SkillInvokeProcessor":
                result_prop = getattr(p, "result_property", None)
                if result_prop:
                    set_props[result_prop] = i
            elif type_name == "MemoryRecallProcessor":
                result_prop = getattr(p, "result_property", None)
                if result_prop:
                    set_props[result_prop] = i
            elif type_name == "AgentRunProcessor":
                result_prop = getattr(p, "result_property", None)
                if result_prop:
                    set_props[result_prop] = i
            elif type_name == "AIRpaProcessor":
                action_prop = getattr(p, "action_property", None)
                if action_prop:
                    set_props[action_prop] = i

        # Собираем все чтения свойств
        read_props: set[str] = set()
        for i, p in enumerate(pipeline.processors):
            type_name = type(p).__name__
            patterns = _PROPERTY_READ_PATTERNS.get(type_name, [])
            for attr_name in patterns:
                value = getattr(p, attr_name, None)
                if value is None:
                    continue
                # Обрабатываем строковые значения с potential property references
                prop_refs = self._extract_property_references(str(value))
                read_props.update(prop_refs)

            # Дополнительные проверки для процессоров с динамическим чтением
            if type_name == "SetPropertyProcessor":
                # SetPropertyProcessor может читать source_property
                source = getattr(p, "source_property", None)
                if source:
                    prop_refs = self._extract_property_references(str(source))
                    read_props.update(prop_refs)

        # Находим неиспользованные свойства
        unused_props = set(set_props.keys()) - read_props
        for prop_name in unused_props:
            proc_idx = set_props[prop_name]
            issues.append(
                LintIssue(
                    code="W003",
                    severity="warning",
                    message=f"Свойство '{prop_name}' устанавливается но никогда не читается",
                    suggestion="Проверьте что результат используется в последующих процессорах, "
                    "или удалите лишний set_property",
                    processor_index=proc_idx,
                )
            )

    def _extract_property_references(self, value: str) -> set[str]:
        """Извлекает property references из строки.

        Поддерживает форматы:
        - property:foo -> foo
        - ${property:foo} -> foo
        - body.field -> body (и field)
        - ${body.field} -> body (и field)
        """
        refs: set[str] = set()

        # property:foo или ${property:foo}
        prop_pattern = r"(?:\$\{)?property:([a-zA-Z_][a-zA-Z0-9_]*)\}?"
        for match in re.finditer(prop_pattern, value):
            refs.add(match.group(1))

        # body.field или ${body.field} - извлекаем только body как reference
        body_pattern = r"(?:\$\{)?body(?:\.([a-zA-Z_][a-zA-Z0-9_]*))?\}?"
        for match in re.finditer(body_pattern, value):
            refs.add("body")

        return refs

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
