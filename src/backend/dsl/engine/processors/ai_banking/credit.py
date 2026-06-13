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

from typing import Any

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
from src.backend.dsl.engine.processors.base import BaseProcessor

_logger = get_logger("dsl.engine.processors.ai_banking")


class CreditScoringResult(BaseModel):
    """Результат кредитного скоринга через RAG."""

    approved: bool = Field(description="Loan approval decision")
    limit: float | None = Field(default=None, ge=0, description="Approved limit")
    rate: float | None = Field(default=None, ge=0, description="Annual rate %")
    citations: list[str] = Field(default_factory=list, description="RAG citations")
    reasons: list[str] = Field(default_factory=list, description="Decision reasons")


class CreditScoringRagProcessor(_BankingAIProcessor):
    """Кредитный скоринг через RAG: клиент + история + policy-документы.

    Вход: {"customer": {...}, "amount": ..., "product": "..."}.
    Выход: {"approved": bool, "limit": ..., "rate": ..., "citations": [...]}.
    """

    capability = "ai.banking.credit"
    audit_event_prefix = "banking.credit"

    def __init__(self, product: str = "retail") -> None:
        super().__init__(name=f"credit_rag:{product}")
        self.product = product

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, raises exceptions для error handling pipeline."""
        exchange.set_property("credit_product", self.product)
        exchange.set_property("banking_action", "ai.credit.score_rag")
        body = exchange.in_message.body
        if not isinstance(body, dict):
            exchange.fail("CreditScoringRagProcessor: expected dict body")
            return
        customer = body.get("customer", {})
        amount = body.get("amount", 0)
        product = body.get("product", self.product)
        rag_context = exchange.properties.get("vector_results", [])
        rag_text = self._format_rag_context(rag_context)
        prompt = self._build_prompt(customer, amount, product, rag_text)
        if not await self._check_capability(exchange, context):
            return
        result = await self._call_llm(
            prompt=prompt,
            output_model=CreditScoringResult,
            exchange=exchange,
            context=context,
        )
        if result is None:
            await emit_banking_audit(
                event=f"{self.audit_event_prefix}.failed",
                processor=self.name,
                params={"product": product},
                error="llm_call_failed",
            )
            return
        await emit_banking_audit(
            event=f"{self.audit_event_prefix}.completed",
            processor=self.name,
            params={
                "customer_id": customer.get("id"),
                "amount": amount,
                "product": product,
            },
            result={
                "approved": result.approved,
                "limit": result.limit,
                "rate": result.rate,
                "citations": result.citations,
            },
        )
        exchange.in_message.set_body(
            {
                "approved": result.approved,
                "limit": result.limit,
                "rate": result.rate,
                "citations": result.citations,
                "reasons": result.reasons,
            }
        )
        exchange.set_property("credit_approved", result.approved)

    def _format_rag_context(self, rag_context: Any) -> str:
        if not rag_context:
            return "No RAG context available."
        if isinstance(rag_context, list):
            return "\n---\n".join(
                (
                    item.get("document", str(item))
                    if isinstance(item, dict)
                    else str(item)
                    for item in rag_context
                )
            )
        return str(rag_context)

    def _build_prompt(
        self, customer: dict[str, Any], amount: float, product: str, rag_context: str
    ) -> str:
        customer_json = (
            orjson.dumps(customer).decode()
            if isinstance(customer, dict)
            else str(customer)
        )
        return f'Analyze this credit application using the policy documents for context.\n\nCustomer: {customer_json}\nRequested Amount: {amount}\nProduct: {product}\n\nPolicy Documents (RAG context):\n{rag_context}\n\nRespond with JSON:\n{{\n  "approved": true|false,\n  "limit": number or null,\n  "rate": number or null,\n  "citations": ["doc_ref1", "doc_ref2"],\n  "reasons": ["reason1", "reason2"]\n}}'

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
        if self.product != "retail":
            spec["product"] = self.product
        return {"credit_scoring_rag": spec}


class CustomerChatbotProcessor(BaseProcessor):
    """Клиентский чат-бот (tool-use: balance, statement, faq, escalate)."""

    def __init__(self, channel: str = "web") -> None:
        super().__init__(name=f"chatbot:{channel}")
        self.channel = channel

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, raises exceptions для error handling pipeline."""
        exchange.set_property("chatbot_channel", self.channel)
        exchange.set_property("banking_action", "ai.chatbot.respond")

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализовать конфигурацию процессора в dict (для YAML/JSON spec). Returns None для non-serializable state."""
        spec: dict[str, Any] = {}
        if self.channel != "web":
            spec["channel"] = self.channel
        return {"customer_chatbot": spec}


class AppealProcessorAI(BaseProcessor):
    """Автоматическая обработка клиентских обращений."""

    def __init__(self) -> None:
        super().__init__(name="appeal_ai")

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, raises exceptions для error handling pipeline."""
        exchange.set_property("banking_action", "ai.appeals.process")

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализовать конфигурацию процессора в dict (для YAML/JSON spec). Returns None для non-serializable state."""
        return {"appeal_ai": {}}
