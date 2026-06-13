"""AI-пайплайны для банковского домена (K4 S19 W3, S-L4-1).

Каждый процессор выполняет:
- LLM call с retry и rate-limit detection
- Structured output через Pydantic
- capability-gate ai.banking.* (ai.banking.kyc_aml, ai.banking.antifraud, etc.)
- audit-event banking.*
- cost budget tracking

Процессоры:
- KYC/AML verification (документы → decision + score)
- Anti-fraud LLM scoring (транзакция → risk score + explanation)
- Credit scoring via RAG (клиент + история → решение + cited reasons)
- Document classification (документ → тип + confidence)
- Francotyping (текст → язык/регион/классификация)
"""

from __future__ import annotations

from typing import Any, TypeVar

import orjson
from pydantic import BaseModel, Field

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.core.audit.facade import (
    emit_banking_audit,  # S109 W2: migrated to canonical facade
)
from src.backend.dsl.engine.processors.ai_banking._base import (
    _BankingAIProcessor,  # S50 W3: base class
)

_logger = get_logger("dsl.engine.processors.ai_banking")
_T = TypeVar("_T", bound=BaseModel)


class KycAmlResult(BaseModel):
    """Результат KYC/AML верификации."""

    decision: str = Field(description="approve|review|reject")
    score: float = Field(ge=0.0, le=1.0, description="AML risk score")
    reasons: list[str] = Field(default_factory=list, description="Decision reasons")
    kyc_jurisdiction: str | None = Field(default=None, description="Jurisdiction code")


class KycAmlVerifyProcessor(_BankingAIProcessor):
    """KYC/AML верификация клиента.

    Вход: {"documents": [...], "customer": {...}}.
    Выход: {"decision": "approve"|"review"|"reject", "score": float, "reasons": [...]}

    Требует capability: ai.banking.kyc_aml
    """

    capability = "ai.banking.kyc_aml"
    audit_event_prefix = "banking.kyc_aml"

    def __init__(self, jurisdiction: str = "ru", model: str | None = None) -> None:
        super().__init__(name=f"kyc_aml:{jurisdiction}")
        self.jurisdiction = jurisdiction
        self.model = model

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, raises exceptions для error handling pipeline."""
        exchange.set_property("kyc_jurisdiction", self.jurisdiction)
        exchange.set_property("banking_action", "ai.kyc_aml.verify")
        body = exchange.in_message.body
        if not isinstance(body, dict):
            exchange.fail("KycAmlVerifyProcessor: expected dict body")
            return
        documents = body.get("documents", [])
        customer = body.get("customer", {})
        prompt = self._build_prompt(customer, documents)
        if not await self._check_capability(exchange, context):
            return
        result = await self._call_llm(
            prompt=prompt,
            output_model=KycAmlResult,
            exchange=exchange,
            context=context,
            model=self.model,
        )
        if result is None:
            await emit_banking_audit(
                event=f"{self.audit_event_prefix}.failed",
                processor=self.name,
                params={"jurisdiction": self.jurisdiction},
                error="llm_call_failed",
            )
            return
        await emit_banking_audit(
            event=f"{self.audit_event_prefix}.completed",
            processor=self.name,
            params={
                "jurisdiction": self.jurisdiction,
                "customer_id": customer.get("id"),
            },
            result={
                "decision": result.decision,
                "score": result.score,
                "reasons": result.reasons,
            },
        )
        exchange.in_message.set_body(
            {
                "decision": result.decision,
                "score": result.score,
                "reasons": result.reasons,
            }
        )
        exchange.set_property("kyc_decision", result.decision)
        exchange.set_property("kyc_score", result.score)

    def _build_prompt(
        self, customer: dict[str, Any], documents: list[dict[str, Any]]
    ) -> str:
        customer_info = (
            orjson.dumps(customer).decode()
            if isinstance(customer, dict)
            else str(customer)
        )
        docs_info = (
            orjson.dumps(documents).decode()
            if isinstance(documents, list)
            else str(documents)
        )
        return f'Analyze the following customer and documents for KYC/AML verification.\n\nCustomer: {customer_info}\n\nDocuments: {docs_info}\n\nJurisdiction: {self.jurisdiction}\n\nRespond with JSON:\n{{\n  "decision": "approve|review|reject",\n  "score": 0.0-1.0,\n  "reasons": ["reason1", "reason2"],\n  "kyc_jurisdiction": "{self.jurisdiction}"\n}}'

    async def _check_capability(
        self, exchange: Exchange[Any], context: ExecutionContext
    ) -> bool:
        """Verify ai.banking.kyc_aml capability."""
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
        """Сериализовать конфигурацию процессора в dict (для YAML/JSON spec). Returns None для non-serializable state."""
        spec: dict[str, Any] = {}
        if self.jurisdiction != "ru":
            spec["jurisdiction"] = self.jurisdiction
        return {"kyc_aml_verify": spec}


class AntiFraudResult(BaseModel):
    """Результат anti-fraud скоринга."""

    risk_score: float = Field(ge=0.0, le=1.0, description="Fraud risk score")
    risk_level: str = Field(description="low|medium|high|critical")
    explanation: str = Field(description="Human-readable explanation")
    triggered_rules: list[str] = Field(default_factory=list)


class AntiFraudScoreProcessor(_BankingAIProcessor):
    """LLM-скоринг антифрода поверх детерминистических правил.

    Детерминистические правила живут в `core.security.banking.AntiFraudEngine`;
    этот процессор добавляет LLM-layer для граничных случаев (review).
    """

    capability = "ai.banking.antifraud"
    audit_event_prefix = "banking.antifraud"

    def __init__(self, model: str = "default") -> None:
        super().__init__(name=f"antifraud_llm:{model}")
        self.model = model

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, raises exceptions для error handling pipeline."""
        exchange.set_property("antifraud_model", self.model)
        exchange.set_property("banking_action", "ai.antifraud.score")
        body = exchange.in_message.body
        if not isinstance(body, dict):
            exchange.fail("AntiFraudScoreProcessor: expected dict body")
            return
        transaction = body.get("transaction", {})
        history = body.get("history", [])
        rules_triggered = body.get("triggered_rules", [])
        prompt = self._build_prompt(transaction, history, rules_triggered)
        if not await self._check_capability(exchange, context):
            return
        result = await self._call_llm(
            prompt=prompt,
            output_model=AntiFraudResult,
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
            params={"transaction_id": transaction.get("id")},
            result={
                "risk_score": result.risk_score,
                "risk_level": result.risk_level,
                "triggered_rules": result.triggered_rules,
            },
        )
        exchange.in_message.set_body(
            {
                "risk_score": result.risk_score,
                "risk_level": result.risk_level,
                "explanation": result.explanation,
                "triggered_rules": result.triggered_rules,
            }
        )
        exchange.set_property("fraud_risk_score", result.risk_score)
        exchange.set_property("fraud_risk_level", result.risk_level)

    def _build_prompt(
        self,
        transaction: dict[str, Any],
        history: list[dict[str, Any]],
        rules_triggered: list[str],
    ) -> str:
        tx_json = (
            orjson.dumps(transaction).decode()
            if isinstance(transaction, dict)
            else str(transaction)
        )
        hist_json = (
            orjson.dumps(history).decode()
            if isinstance(history, list)
            else str(history)
        )
        rules_json = (
            orjson.dumps(rules_triggered).decode()
            if isinstance(rules_triggered, list)
            else str(rules_triggered)
        )
        return f'Analyze this transaction for fraud risk.\n\nTransaction: {tx_json}\nHistory: {hist_json}\nTriggered Rules: {rules_json}\n\nRespond with JSON:\n{{\n  "risk_score": 0.0-1.0,\n  "risk_level": "low|medium|high|critical",\n  "explanation": "human-readable explanation",\n  "triggered_rules": ["additional_rules_if_any"]\n}}'

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
        """Сериализовать конфигурацию процессора в dict (для YAML/JSON spec). Returns None для non-serializable state."""
        spec: dict[str, Any] = {}
        if self.model != "default":
            spec["model"] = self.model
        return {"antifraud_score": spec}
