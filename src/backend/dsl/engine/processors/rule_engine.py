"""DSL processor ``evaluate_rules`` (S8 rule-engine scaffold).

Wave: ``[wave:s8/rule-engine-scaffold]``. Минимальный безопасный evaluator
выражений поверх библиотеки :mod:`simpleeval` (уже в lock-файле как
transitive-зависимость). Reference use-case — credit_scoring ruleset.

Поддерживает простые булевы и арифметические выражения над переменными
из ``exchange.in_message.body``. На первое успешно выполненное правило срабатывает
``on_match`` (имя action или dotted-path-action), либо в ``exchange.in_message.body``
проставляется ``decision``/``matched_rule``.

Использование в YAML::

    steps:
      - evaluate_rules:
          rules:
            - name: high_income_low_debt
              expr: "income > 100000 and debt_ratio < 0.3"
              decision: APPROVE
            - name: low_score
              expr: "credit_score < 500"
              decision: REJECT
          context_from: body.applicant
          decision_to: body.decision

Использование в Python-builder::

    RouteBuilder("credit_score") \\
        .from_("http:POST /api/v1/credit/score") \\
        .evaluate_rules(rules=[
            Rule(name="approve", expr="score > 700", decision="APPROVE"),
            Rule(name="reject", expr="score < 500", decision="REJECT"),
        ], context_from="body.applicant", decision_to="body.decision")

Безопасность:

* ``SimpleEval`` запрещает ``import``, ``exec``, ``eval``, доступ к ``__``;
* ограниченный набор операторов и функций;
* нет subprocess/file access (S4 R-V15-4 — code execution только sandboxed).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.engine.processors.documents import _resolve_path, _set_path
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


__all__ = ("EvaluateRulesParams", "EvaluateRulesProcessor", "Rule")


class Rule(BaseModel):
    """Одно правило rule-engine.

    Атрибуты:
        name: Идентификатор правила (используется для трассировки).
        expr: Булево выражение SimpleEval над переменными из контекста.
        decision: Метка решения, проставляется при совпадении.
    """

    name: str
    expr: str
    decision: str


class EvaluateRulesParams(BaseModel):
    """Параметры DSL-шага ``evaluate_rules``.

    Атрибуты:
        rules: Упорядоченный список правил (first-match-wins).
        context_from: dotted-path в exchange.in_message.body к dict с переменными.
            Если None — используется весь ``exchange.in_message.body``.
        decision_to: dotted-path для записи матча.
        default_decision: Значение, если ни одно правило не сработало.
    """

    rules: list[Rule] = Field(default_factory=list)
    context_from: str | None = None
    decision_to: str = "decision"
    default_decision: str = "NO_MATCH"


@processor(name="evaluate_rules")
class EvaluateRulesProcessor(BaseProcessor):
    """Last-resort safe-eval rule engine для DSL-pipeline.

    First-match-wins: правила обходятся по порядку, первое истинное
    выражение фиксирует ``decision`` и прерывает обход.

    Ошибки парсинга/eval отдельного правила НЕ останавливают остальные
    (логируются и пропускаются — соответствует best-effort семантике
    decision-engine).
    """

    name = "evaluate_rules"

    def __init__(self, params: EvaluateRulesParams) -> None:
        super().__init__(name=self.name)
        self.params = params

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from simpleeval import SimpleEval  # lazy-import

        ctx_dict = _resolve_path(exchange.in_message.body, self.params.context_from)
        if not isinstance(ctx_dict, dict):
            ctx_dict = {}

        evaluator = SimpleEval(names=ctx_dict)
        matched: Rule | None = None
        for rule in self.params.rules:
            try:
                if bool(evaluator.eval(rule.expr)):
                    matched = rule
                    break
            except Exception as _:
                continue

        decision = matched.decision if matched else self.params.default_decision
        if exchange.in_message.body is None:
            exchange.in_message.body = {}
        _set_path(exchange.in_message.body, self.params.decision_to, decision)
        if matched is not None:
            _set_path(exchange.in_message.body, "matched_rule", matched.name)

    def to_spec(self) -> dict[str, Any]:
        return {
            "evaluate_rules": {
                "rules": [r.model_dump() for r in self.params.rules],
                "context_from": self.params.context_from,
                "decision_to": self.params.decision_to,
                "default_decision": self.params.default_decision,
            }
        }
