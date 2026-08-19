"""Loan eligibility processor — мигрирован из S59 banking_processors на S50 base."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.backend.core.audit.facade import emit_banking_audit
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.ai_banking._base import _BankingAIProcessor


class LoanEligibilityResult(BaseModel):
    """Результат проверки eligibility для кредита."""

    eligible: bool = Field(description="Одобрен ли кредит")
    max_amount: float = Field(ge=0.0, description="Максимальная сумма")
    interest_rate: float = Field(ge=0.0, description="Процентная ставка (годовая)")
    term_months: int = Field(ge=1, description="Срок в месяцах")
    decision_reasons: list[str] = Field(
        default_factory=list, description="Основные причины решения"
    )
    conditions: list[str] = Field(default_factory=list, description="Условия кредита")


class LoanEligibilityProcessor(_BankingAIProcessor):
    """Проверка eligibility — определение условий кредита.

    Вход: {"credit_score": int, "annual_income": float,
           "requested_amount": float, "loan_term_months": int,
           "existing_debt": float, "employment_status": str}.
    Выход: {"eligible": bool, "max_amount": float, "interest_rate": float,
            "term_months": int, "decision_reasons": [...], "conditions": [...]}.
    """

    capability = "ai.banking.loan_eligibility"
    audit_event_prefix = "banking.loan_eligibility"

    def __init__(self, model: str | None = None) -> None:
        super().__init__(name="loan_eligibility")
        self.model = model

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Оценивает eligibility по кредиту через LLM и записывает результат с audit-событием.

        Args:
            exchange: Текущий обмен с параметрами заявки.
            context: Контекст выполнения процессора.

        """
        exchange.set_property("banking_action", "ai.loan.eligibility")
        body = exchange.in_message.body
        if not isinstance(body, dict):
            exchange.fail("LoanEligibilityProcessor: expected dict body")
            return
        prompt = self._build_prompt(body)
        if not await self._check_capability(exchange, context):
            return
        result = await self._call_llm(
            prompt=prompt,
            output_model=LoanEligibilityResult,
            exchange=exchange,
            context=context,
            model=self.model,
        )
        if result is None:
            await emit_banking_audit(
                event=f"{self.audit_event_prefix}.failed",
                processor=self.name,
                params={},
                error="llm_call_failed",
            )
            return
        await emit_banking_audit(
            event=f"{self.audit_event_prefix}.completed",
            processor=self.name,
            params={"requested_amount": body.get("requested_amount")},
            result={
                "eligible": result.eligible,
                "max_amount": result.max_amount,
                "interest_rate": result.interest_rate,
            },
        )
        exchange.in_message.set_body(
            {
                "eligible": result.eligible,
                "max_amount": result.max_amount,
                "interest_rate": result.interest_rate,
                "term_months": result.term_months,
                "decision_reasons": result.decision_reasons,
                "conditions": result.conditions,
            }
        )
        exchange.set_property("loan_eligible", result.eligible)
        exchange.set_property("loan_max_amount", result.max_amount)

    def _build_prompt(self, body: dict[str, Any]) -> str:
        # S227 cycle 14 (D432): per-field 1000-char truncation prevents
        # prompt-injection via oversized string fields + matches the
        # document.py pattern. Each field is truncated to keep prompt total
        # bounded.
        def _t(v: Any) -> str:
            s = str(v) if v is not None else ""
            return s[:1000] if len(s) > 1000 else s

        return (
            "Определи eligibility для кредита и предложи условия.\n\n"
            f"- кредитный балл: {_t(body.get('credit_score'))}\n"
            f"- годовой доход: {_t(body.get('annual_income'))}\n"
            f"- запрошенная сумма: {_t(body.get('requested_amount'))}\n"
            f"- желаемый срок: {_t(body.get('loan_term_months'))} месяцев\n"
            f"- текущий долг: {_t(body.get('existing_debt'))}\n"
            f"- статус занятости: {_t(body.get('employment_status'))}\n\n"
            "Верни JSON:\n"
            "{\n"
            '  "eligible": true|false,\n'
            '  "max_amount": number,\n'
            '  "interest_rate": number,\n'
            '  "term_months": int,\n'
            '  "decision_reasons": ["reason1", "reason2"],\n'
            '  "conditions": ["condition1"]\n'
            "}"
        )

    async def _check_capability(
        self, exchange: Exchange[Any], context: ExecutionContext
    ) -> bool:
        """Verify capability (S190 — unified facade pattern).

        Мигрировано с inline gate.check() на CapabilityFacade.check_or_raise()
        для unified capability semantics + plugin attribution.
        """
        return await self._check_capability_via_facade(exchange)


def to_spec(self) -> dict[str, Any] | None:
    """Метод to_spec (см. signature)."""
    spec: dict[str, Any] = {}
    if self.model:
        spec["model"] = self.model
    return {"loan_eligibility": spec}
