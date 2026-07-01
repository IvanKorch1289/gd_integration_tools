"""Risk assessment processor — мигрирован из S59 banking_processors на S50 base."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.backend.core.audit.facade import emit_banking_audit
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.ai_banking._base import _BankingAIProcessor


class RiskAssessmentResult(BaseModel):
    """Результат комплексной оценки рисков."""

    risk_level: str = Field(description="low / medium / high / critical")
    risk_score: float = Field(ge=0.0, le=1.0, description="Численный score риска")
    risk_factors: list[str] = Field(default_factory=list, description="Факторы риска")
    mitigation_suggestions: list[str] = Field(
        default_factory=list, description="Рекомендации по снижению"
    )


class RiskAssessmentProcessor(_BankingAIProcessor):
    """Комплексная оценка рисков по кредитной заявке.

    Вход: {"customer_profile": str, "loan_amount": float,
           "loan_purpose": str, "collateral_value": float,
           "market_conditions": str}.
    Выход: {"risk_level": str, "risk_score": float,
            "risk_factors": [...], "mitigation_suggestions": [...]}.
    """

    capability = "ai.banking.risk"
    audit_event_prefix = "banking.risk"

    def __init__(self, model: str | None = None) -> None:
        super().__init__(name="risk_assessment")
        self.model = model

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Оценивает кредитный риск через LLM с audit-событиями."""
        exchange.set_property("banking_action", "ai.risk.assess")
        body = exchange.in_message.body
        if not isinstance(body, dict):
            exchange.fail("RiskAssessmentProcessor: expected dict body")
            return
        prompt = self._build_prompt(body)
        if not await self._check_capability(exchange, context):
            return
        result = await self._call_llm(
            prompt=prompt,
            output_model=RiskAssessmentResult,
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
            params={"loan_amount": body.get("loan_amount")},
            result={
                "risk_level": result.risk_level,
                "risk_score": result.risk_score,
            },
        )
        exchange.in_message.set_body(
            {
                "risk_level": result.risk_level,
                "risk_score": result.risk_score,
                "risk_factors": result.risk_factors,
                "mitigation_suggestions": result.mitigation_suggestions,
            }
        )
        exchange.set_property("risk_level", result.risk_level)
        exchange.set_property("risk_score", result.risk_score)

    def _build_prompt(self, body: dict[str, Any]) -> str:
        return (
            "Проведи комплексную оценку рисков по кредитной заявке.\n\n"
            f"- профиль клиента: {body.get('customer_profile', '')}\n"
            f"- запрошенная сумма: {body.get('loan_amount', '')}\n"
            f"- цель кредита: {body.get('loan_purpose', '')}\n"
            f"- стоимость залога: {body.get('collateral_value', '')}\n"
            f"- рыночные условия: {body.get('market_conditions', '')}\n\n"
            "Верни JSON:\n"
            '{\n'
            '  "risk_level": "low|medium|high|critical",\n'
            '  "risk_score": 0.0-1.0,\n'
            '  "risk_factors": ["factor1", "factor2"],\n'
            '  "mitigation_suggestions": ["suggestion1", "suggestion2"]\n'
            '}'
        )

    async def _check_capability(
        self, exchange: Exchange[Any], context: ExecutionContext
    ) -> bool:
        try:
            from src.backend.core.security.capabilities import CapabilityGate

            gate = CapabilityGate()
            gate.check(self.capability, scope=None)
            return True
        except Exception as exc:
            exchange.fail(f"capability_denied: {self.capability} - {exc}")
            await emit_banking_audit(
                event=f"{self.audit_event_prefix}.capability_denied",
                processor=self.name,
                params={},
                error=str(exc),
            )
            return False

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {}
        if self.model:
            spec["model"] = self.model
        return {"risk_assessment": spec}
