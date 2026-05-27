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

import logging
from typing import Any, Literal

import orjson
from pydantic import BaseModel, Field

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

__all__ = (
    "KycAmlVerifyProcessor",
    "AntiFraudScoreProcessor",
    "CreditScoringRagProcessor",
    "DocumentClassifierProcessor",
    "FrancotypingProcessor",
    "CustomerChatbotProcessor",
    "AppealProcessorAI",
    "TransactionCategorizerProcessor",
    "FinDocOcrLlmProcessor",
)

_logger = logging.getLogger("dsl.engine.processors.ai_banking")

# ─── Pydantic models for structured output ─────────────────────────────────────


class KycAmlResult(BaseModel):
    """Результат KYC/AML верификации."""

    decision: str = Field(description="approve|review|reject")
    score: float = Field(ge=0.0, le=1.0, description="AML risk score")
    reasons: list[str] = Field(default_factory=list, description="Decision reasons")
    kyc_jurisdiction: str | None = Field(default=None, description="Jurisdiction code")


class AntiFraudResult(BaseModel):
    """Результат anti-fraud скоринга."""

    risk_score: float = Field(ge=0.0, le=1.0, description="Fraud risk score")
    risk_level: str = Field(description="low|medium|high|critical")
    explanation: str = Field(description="Human-readable explanation")
    triggered_rules: list[str] = Field(default_factory=list)


class CreditScoringResult(BaseModel):
    """Результат кредитного скоринга через RAG."""

    approved: bool = Field(description="Loan approval decision")
    limit: float | None = Field(default=None, ge=0, description="Approved limit")
    rate: float | None = Field(default=None, ge=0, description="Annual rate %")
    citations: list[str] = Field(default_factory=list, description="RAG citations")
    reasons: list[str] = Field(default_factory=list, description="Decision reasons")


class DocumentClassifierResult(BaseModel):
    """Результат классификации документа."""

    document_type: str = Field(description="passport| driver's_license|invoice|contract|statement|other")
    confidence: float = Field(ge=0.0, le=1.0, description="Classification confidence")
    subtypes: list[str] = Field(default_factory=list, description="Additional type info")
    extracted_fields: dict[str, str] = Field(default_factory=dict)


class FrancotypingResult(BaseModel):
    """Результат франкотипирования текста."""

    language: str = Field(description="ISO 639-1 language code")
    region: str | None = Field(default=None, description="Region/dialect code")
    script: str = Field(description="Latin|Cyrillic|Arabic|Han|etc.")
    classification: str = Field(description="top-level classification")
    confidence: float = Field(ge=0.0, le=1.0)


# ─── Audit helper ───────────────────────────────────────────────────────────────


async def _emit_audit(
    event: str,
    processor: str,
    params: dict[str, Any],
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    """Эмитит audit-event для banking AI процессоров.

    Args:
        event: Event name (e.g., "banking.kyc_aml.verify").
        processor: Processor name.
        params: Input parameters.
        result: Optional result data.
        error: Optional error message.
    """
    try:
        from src.backend.services.audit.audit_service import AuditService

        # Try to get singleton
        try:
            from src.backend.infrastructure.service_locator import locator

            audit = locator.resolve(AuditService)
        except Exception as _:
            audit = None

        if audit is None:
            _logger.debug("audit service not available: %s", event)
            return

        outcome: Literal["success", "failure", "denied"] = (
            "failure" if error else "success"
        )
        severity: str = "warning" if error else "info"
        payload = {
            "event": event,
            "actor": f"processor:{processor}",
            "resource": f"banking/{processor}",
            "action": event.split(".")[-1] if "." in event else event,
            "outcome": outcome,
            "severity": severity,  # type: ignore[arg-type]
            "details": {
                "processor": processor,
                "params": params,
                "result": result,
                "error": error,
            },
        }
        await audit.emit(**payload)
    except Exception as _:
        _logger.debug("audit emit skipped: %s", event)


# ─── Base class for banking AI processors ─────────────────────────────────────


class _BankingAIProcessor(BaseProcessor):
    """Base class for banking AI processors with common LLM logic."""

    # Subclasses override these
    capability: str = "ai.banking.base"
    audit_event_prefix: str = "banking"

    # Cost per 1K tokens (approximate)
    COST_PER_1K_TOKENS: float = 0.02

    async def _call_llm(
        self,
        prompt: str,
        output_model: type[BaseModel],
        exchange: Exchange[Any],
        context: ExecutionContext,
        model: str | None = None,
    ) -> BaseModel | None:
        """Execute LLM call with structured output.

        Returns:
            Parsed Pydantic model or None on failure.
        """
        from src.backend.infrastructure.resilience.retry import make_async_retry

        try:
            from src.backend.services.ai.ai_agent import get_ai_agent_service
        except ImportError as exc:
            exchange.fail(f"AI agent service unavailable: {exc}")
            return None

        agent = get_ai_agent_service()

        _retryable = (TimeoutError, ConnectionError)

        @make_async_retry(max_attempts=3, initial_backoff=1.0, multiplier=2.0, on=_retryable)
        async def _chat_with_retry() -> Any:
            return await agent.chat(
                messages=[{"role": "user", "content": prompt}],
                model=model or "default",
                response_format=output_model,
            )

        try:
            raw = await _chat_with_retry()
        except RuntimeError as exc:
            if "rate" in str(exc).lower():
                exchange.fail(f"LLM rate limit: {exc}")
            else:
                exchange.fail(f"LLM call failed: {exc}")
            return None
        except (TimeoutError, ConnectionError) as exc:
            exchange.fail(f"LLM call failed after retries: {exc}")
            return None

        # Track cost
        if isinstance(raw, dict):
            usage = raw.get("usage") or {}
            tokens = int(usage.get("total_tokens", 0)) if usage else 0
            if tokens:
                cost = round(tokens * self.COST_PER_1K_TOKENS / 1000, 6)
                exchange.set_property("llm.tokens_used", tokens)
                exchange.set_property("llm.cost_usd", cost)
                exchange.set_property("banking.cost_usd", cost)

        # Parse structured output
        if isinstance(raw, dict):
            try:
                return output_model.model_validate(raw)
            except Exception as exc:
                _logger.warning("structured_output_parse_error: %s", exc)
                # Try to extract JSON from text response
                return self._parse_fallback(raw, output_model)

        # String response - try JSON parse
        if isinstance(raw, str):
            return self._parse_fallback({"text": raw}, output_model)

        return None

    def _parse_fallback(
        self, raw: dict[str, Any], output_model: type[BaseModel]
    ) -> BaseModel | None:
        """Fallback parsing when structured output fails."""
        text = raw.get("text", "") if isinstance(raw, dict) else str(raw)
        # Try to find JSON in text
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                parsed = orjson.loads(text[start:end])
                return output_model.model_validate(parsed)
            except Exception as _:
                pass
        return None


# ─── KYC/AML Processor ─────────────────────────────────────────────────────────


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
        exchange.set_property("kyc_jurisdiction", self.jurisdiction)
        exchange.set_property("banking_action", "ai.kyc_aml.verify")

        # Get input data
        body = exchange.in_message.body
        if not isinstance(body, dict):
            exchange.fail("KycAmlVerifyProcessor: expected dict body")
            return

        documents = body.get("documents", [])
        customer = body.get("customer", {})

        # Build prompt
        prompt = self._build_prompt(customer, documents)

        # Check capability
        if not await self._check_capability(exchange, context):
            return

        # Call LLM
        result = await self._call_llm(
            prompt=prompt,
            output_model=KycAmlResult,
            exchange=exchange,
            context=context,
            model=self.model,
        )

        if result is None:
            await _emit_audit(
                event=f"{self.audit_event_prefix}.failed",
                processor=self.name,
                params={"jurisdiction": self.jurisdiction},
                error="llm_call_failed",
            )
            return

        # Emit audit
        await _emit_audit(
            event=f"{self.audit_event_prefix}.completed",
            processor=self.name,
            params={"jurisdiction": self.jurisdiction, "customer_id": customer.get("id")},
            result={
                "decision": result.decision,
                "score": result.score,
                "reasons": result.reasons,
            },
        )

        # Set result
        exchange.in_message.set_body({
            "decision": result.decision,
            "score": result.score,
            "reasons": result.reasons,
        })
        exchange.set_property("kyc_decision", result.decision)
        exchange.set_property("kyc_score", result.score)

    def _build_prompt(self, customer: dict[str, Any], documents: list[dict[str, Any]]) -> str:
        customer_info = orjson.dumps(customer).decode() if isinstance(customer, dict) else str(customer)
        docs_info = orjson.dumps(documents).decode() if isinstance(documents, list) else str(documents)
        return f"""Analyze the following customer and documents for KYC/AML verification.

Customer: {customer_info}

Documents: {docs_info}

Jurisdiction: {self.jurisdiction}

Respond with JSON:
{{
  "decision": "approve|review|reject",
  "score": 0.0-1.0,
  "reasons": ["reason1", "reason2"],
  "kyc_jurisdiction": "{self.jurisdiction}"
}}"""

    async def _check_capability(self, exchange: Exchange[Any], context: ExecutionContext) -> bool:
        """Verify ai.banking.kyc_aml capability."""
        try:
            from src.backend.core.security.capabilities import CapabilityGate

            gate = CapabilityGate()
            gate.check(self.capability, scope=None)
            return True
        except Exception as exc:
            exchange.fail(f"capability_denied: {self.capability} - {exc}")
            await _emit_audit(
                event=f"{self.audit_event_prefix}.capability_denied",
                processor=self.name,
                params={},
                error=str(exc),
            )
            return False

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {}
        if self.jurisdiction != "ru":
            spec["jurisdiction"] = self.jurisdiction
        return {"kyc_aml_verify": spec}


# ─── Anti-Fraud Processor ─────────────────────────────────────────────────────


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
            await _emit_audit(
                event=f"{self.audit_event_prefix}.failed",
                processor=self.name,
                params={},
                error="llm_call_failed",
            )
            return

        await _emit_audit(
            event=f"{self.audit_event_prefix}.completed",
            processor=self.name,
            params={"transaction_id": transaction.get("id")},
            result={
                "risk_score": result.risk_score,
                "risk_level": result.risk_level,
                "triggered_rules": result.triggered_rules,
            },
        )

        exchange.in_message.set_body({
            "risk_score": result.risk_score,
            "risk_level": result.risk_level,
            "explanation": result.explanation,
            "triggered_rules": result.triggered_rules,
        })
        exchange.set_property("fraud_risk_score", result.risk_score)
        exchange.set_property("fraud_risk_level", result.risk_level)

    def _build_prompt(
        self, transaction: dict[str, Any], history: list[dict[str, Any]], rules_triggered: list[str]
    ) -> str:
        tx_json = orjson.dumps(transaction).decode() if isinstance(transaction, dict) else str(transaction)
        hist_json = orjson.dumps(history).decode() if isinstance(history, list) else str(history)
        rules_json = orjson.dumps(rules_triggered).decode() if isinstance(rules_triggered, list) else str(rules_triggered)
        return f"""Analyze this transaction for fraud risk.

Transaction: {tx_json}
History: {hist_json}
Triggered Rules: {rules_json}

Respond with JSON:
{{
  "risk_score": 0.0-1.0,
  "risk_level": "low|medium|high|critical",
  "explanation": "human-readable explanation",
  "triggered_rules": ["additional_rules_if_any"]
}}"""

    async def _check_capability(self, exchange: Exchange[Any], context: ExecutionContext) -> bool:
        try:
            from src.backend.core.security.capabilities import CapabilityGate
            gate = CapabilityGate()
            gate.check(self.capability, scope=None)
            return True
        except Exception as exc:
            exchange.fail(f"capability_denied: {self.capability} - {exc}")
            await _emit_audit(
                event=f"{self.audit_event_prefix}.capability_denied",
                processor=self.name,
                params={},
                error=str(exc),
            )
            return False

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {}
        if self.model != "default":
            spec["model"] = self.model
        return {"antifraud_score": spec}


# ─── Credit Scoring RAG Processor ──────────────────────────────────────────────


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
        exchange.set_property("credit_product", self.product)
        exchange.set_property("banking_action", "ai.credit.score_rag")

        body = exchange.in_message.body
        if not isinstance(body, dict):
            exchange.fail("CreditScoringRagProcessor: expected dict body")
            return

        customer = body.get("customer", {})
        amount = body.get("amount", 0)
        product = body.get("product", self.product)

        # Get RAG context from exchange properties
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
            await _emit_audit(
                event=f"{self.audit_event_prefix}.failed",
                processor=self.name,
                params={"product": product},
                error="llm_call_failed",
            )
            return

        await _emit_audit(
            event=f"{self.audit_event_prefix}.completed",
            processor=self.name,
            params={"customer_id": customer.get("id"), "amount": amount, "product": product},
            result={
                "approved": result.approved,
                "limit": result.limit,
                "rate": result.rate,
                "citations": result.citations,
            },
        )

        exchange.in_message.set_body({
            "approved": result.approved,
            "limit": result.limit,
            "rate": result.rate,
            "citations": result.citations,
            "reasons": result.reasons,
        })
        exchange.set_property("credit_approved", result.approved)

    def _format_rag_context(self, rag_context: Any) -> str:
        if not rag_context:
            return "No RAG context available."
        if isinstance(rag_context, list):
            return "\n---\n".join(
                item.get("document", str(item)) if isinstance(item, dict) else str(item)
                for item in rag_context
            )
        return str(rag_context)

    def _build_prompt(
        self, customer: dict[str, Any], amount: float, product: str, rag_context: str
    ) -> str:
        customer_json = orjson.dumps(customer).decode() if isinstance(customer, dict) else str(customer)
        return f"""Analyze this credit application using the policy documents for context.

Customer: {customer_json}
Requested Amount: {amount}
Product: {product}

Policy Documents (RAG context):
{rag_context}

Respond with JSON:
{{
  "approved": true|false,
  "limit": number or null,
  "rate": number or null,
  "citations": ["doc_ref1", "doc_ref2"],
  "reasons": ["reason1", "reason2"]
}}"""

    async def _check_capability(self, exchange: Exchange[Any], context: ExecutionContext) -> bool:
        try:
            from src.backend.core.security.capabilities import CapabilityGate
            gate = CapabilityGate()
            gate.check(self.capability, scope=None)
            return True
        except Exception as exc:
            exchange.fail(f"capability_denied: {self.capability} - {exc}")
            await _emit_audit(
                event=f"{self.audit_event_prefix}.capability_denied",
                processor=self.name,
                params={},
                error=str(exc),
            )
            return False

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {}
        if self.product != "retail":
            spec["product"] = self.product
        return {"credit_scoring_rag": spec}


# ─── Document Classifier Processor ──────────────────────────────────────────────


class DocumentClassifierProcessor(_BankingAIProcessor):
    """Классификация документа (паспорт, счёт, договор, etc.).

    Вход: {"document_content": "...", "document_type_hint": "..."}.
    Выход: {"document_type": str, "confidence": float, "subtypes": [...], "extracted_fields": {...}}.
    """

    capability = "ai.banking.doc_classify"
    audit_event_prefix = "banking.doc_classify"

    def __init__(self, model: str | None = None) -> None:
        super().__init__(name="doc_classifier")
        self.model = model

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        exchange.set_property("banking_action", "ai.doc.classify")

        body = exchange.in_message.body
        if not isinstance(body, dict):
            exchange.fail("DocumentClassifierProcessor: expected dict body")
            return

        content = body.get("document_content", "")
        type_hint = body.get("document_type_hint", "")

        if not content:
            exchange.fail("DocumentClassifierProcessor: empty document_content")
            return

        prompt = self._build_prompt(content, type_hint)

        if not await self._check_capability(exchange, context):
            return

        result = await self._call_llm(
            prompt=prompt,
            output_model=DocumentClassifierResult,
            exchange=exchange,
            context=context,
            model=self.model,
        )

        if result is None:
            await _emit_audit(
                event=f"{self.audit_event_prefix}.failed",
                processor=self.name,
                params={"type_hint": type_hint},
                error="llm_call_failed",
            )
            return

        await _emit_audit(
            event=f"{self.audit_event_prefix}.completed",
            processor=self.name,
            params={"type_hint": type_hint},
            result={
                "document_type": result.document_type,
                "confidence": result.confidence,
                "subtypes": result.subtypes,
            },
        )

        exchange.in_message.set_body({
            "document_type": result.document_type,
            "confidence": result.confidence,
            "subtypes": result.subtypes,
            "extracted_fields": result.extracted_fields,
        })
        exchange.set_property("doc_type", result.document_type)
        exchange.set_property("doc_classify_confidence", result.confidence)

    def _build_prompt(self, content: str, type_hint: str) -> str:
        hint_section = f"\nType hint (if any): {type_hint}" if type_hint else ""
        # Truncate content if too long
        truncated = content[:8000] if len(content) > 8000 else content
        return f"""Classify this document and extract key fields.

Document:
{truncated}
{hint_section}

Respond with JSON:
{{
  "document_type": "passport| driver's_license|invoice|contract|statement|receipt|report|other",
  "confidence": 0.0-1.0,
  "subtypes": ["subtype1", "subtype2"],
  "extracted_fields": {{"field_name": "value", ...}}
}}"""

    async def _check_capability(self, exchange: Exchange[Any], context: ExecutionContext) -> bool:
        try:
            from src.backend.core.security.capabilities import CapabilityGate
            gate = CapabilityGate()
            gate.check(self.capability, scope=None)
            return True
        except Exception as exc:
            exchange.fail(f"capability_denied: {self.capability} - {exc}")
            await _emit_audit(
                event=f"{self.audit_event_prefix}.capability_denied",
                processor=self.name,
                params={},
                error=str(exc),
            )
            return False


# ─── Francotyping Processor ────────────────────────────────────────────────────


class FrancotypingProcessor(_BankingAIProcessor):
    """Франкотипирование текста: определение языка, региона, скрипта.

    Вход: {"text": "..."}.
    Выход: {"language": str, "region": str|None, "script": str, "classification": str, "confidence": float}.
    """

    capability = "ai.banking.francotype"
    audit_event_prefix = "banking.francotype"

    def __init__(self, model: str | None = None) -> None:
        super().__init__(name="francotype")
        self.model = model

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        exchange.set_property("banking_action", "ai.francotype.analyze")

        body = exchange.in_message.body
        if not isinstance(body, dict):
            exchange.fail("FrancotypingProcessor: expected dict body")
            return

        text = body.get("text", "")

        if not text:
            exchange.fail("FrancotypingProcessor: empty text")
            return

        prompt = self._build_prompt(text)

        if not await self._check_capability(exchange, context):
            return

        result = await self._call_llm(
            prompt=prompt,
            output_model=FrancotypingResult,
            exchange=exchange,
            context=context,
            model=self.model,
        )

        if result is None:
            await _emit_audit(
                event=f"{self.audit_event_prefix}.failed",
                processor=self.name,
                params={},
                error="llm_call_failed",
            )
            return

        await _emit_audit(
            event=f"{self.audit_event_prefix}.completed",
            processor=self.name,
            params={"text_length": len(text)},
            result={
                "language": result.language,
                "region": result.region,
                "script": result.script,
                "confidence": result.confidence,
            },
        )

        exchange.in_message.set_body({
            "language": result.language,
            "region": result.region,
            "script": result.script,
            "classification": result.classification,
            "confidence": result.confidence,
        })
        exchange.set_property("francotype_lang", result.language)
        exchange.set_property("francotype_script", result.script)

    def _build_prompt(self, text: str) -> str:
        truncated = text[:5000] if len(text) > 5000 else text
        return f"""Analyze this text for language, region, and script classification.

Text:
{truncated}

Respond with JSON:
{{
  "language": "ISO 639-1 code (e.g., ru, en, fr, de)",
  "region": "region code or null (e.g., RU, US, GB)",
  "script": "Latin|Cyrillic|Arabic|Han|Hebrew|Greek|Armenian|Japanese|Korean|Thai",
  "classification": "top-level category",
  "confidence": 0.0-1.0
}}"""

    async def _check_capability(self, exchange: Exchange[Any], context: ExecutionContext) -> bool:
        try:
            from src.backend.core.security.capabilities import CapabilityGate
            gate = CapabilityGate()
            gate.check(self.capability, scope=None)
            return True
        except Exception as exc:
            exchange.fail(f"capability_denied: {self.capability} - {exc}")
            await _emit_audit(
                event=f"{self.audit_event_prefix}.capability_denied",
                processor=self.name,
                params={},
                error=str(exc),
            )
            return False


# ─── Legacy processors ( stubs — kept for backwards compatibility) ─────────────


class CustomerChatbotProcessor(BaseProcessor):
    """Клиентский чат-бот (tool-use: balance, statement, faq, escalate)."""

    def __init__(self, channel: str = "web") -> None:
        super().__init__(name=f"chatbot:{channel}")
        self.channel = channel

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        exchange.set_property("chatbot_channel", self.channel)
        exchange.set_property("banking_action", "ai.chatbot.respond")

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {}
        if self.channel != "web":
            spec["channel"] = self.channel
        return {"customer_chatbot": spec}


class AppealProcessorAI(BaseProcessor):
    """Автоматическая обработка клиентских обращений."""

    def __init__(self) -> None:
        super().__init__(name="appeal_ai")

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        exchange.set_property("banking_action", "ai.appeals.process")

    def to_spec(self) -> dict[str, Any] | None:
        return {"appeal_ai": {}}


class TransactionCategorizerProcessor(BaseProcessor):
    """Категоризация транзакций (MCC + subcategory + merchant normalization)."""

    def __init__(self, taxonomy: str = "mcc") -> None:
        super().__init__(name=f"tx_cat:{taxonomy}")
        self.taxonomy = taxonomy

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        exchange.set_property("tx_taxonomy", self.taxonomy)
        exchange.set_property("banking_action", "ai.tx.categorize")

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {}
        if self.taxonomy != "mcc":
            spec["taxonomy"] = self.taxonomy
        return {"tx_categorize": spec}


class FinDocOcrLlmProcessor(BaseProcessor):
    """OCR + LLM для финансовых документов (счета, договоры, выписки)."""

    def __init__(self, doc_type: str = "invoice") -> None:
        super().__init__(name=f"findoc_ocr:{doc_type}")
        self.doc_type = doc_type

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        exchange.set_property("findoc_type", self.doc_type)
        exchange.set_property("banking_action", "ai.findoc.ocr_and_extract")

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {}
        if self.doc_type != "invoice":
            spec["doc_type"] = self.doc_type
        return {"findoc_ocr_llm": spec}
