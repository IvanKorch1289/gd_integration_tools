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

from pydantic import BaseModel, Field

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.ai_banking._audit import (
    _emit_audit,  # S50 W3: cross-module dep
)
from src.backend.dsl.engine.processors.ai_banking._base import (
    _BankingAIProcessor,  # S50 W3: base class
)
from src.backend.dsl.engine.processors.base import BaseProcessor

_logger = get_logger("dsl.engine.processors.ai_banking")


class DocumentClassifierResult(BaseModel):
    """Результат классификации документа."""

    document_type: str = Field(
        description="passport| driver's_license|invoice|contract|statement|other"
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Classification confidence")
    subtypes: list[str] = Field(
        default_factory=list, description="Additional type info"
    )
    extracted_fields: dict[str, str] = Field(default_factory=dict)


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
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, raises exceptions для error handling pipeline."""
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
        exchange.in_message.set_body(
            {
                "document_type": result.document_type,
                "confidence": result.confidence,
                "subtypes": result.subtypes,
                "extracted_fields": result.extracted_fields,
            }
        )
        exchange.set_property("doc_type", result.document_type)
        exchange.set_property("doc_classify_confidence", result.confidence)

    def _build_prompt(self, content: str, type_hint: str) -> str:
        hint_section = f"\nType hint (if any): {type_hint}" if type_hint else ""
        truncated = content[:8000] if len(content) > 8000 else content
        return f"""Classify this document and extract key fields.\n\nDocument:\n{truncated}\n{hint_section}\n\nRespond with JSON:\n{{\n  "document_type": "passport| driver's_license|invoice|contract|statement|receipt|report|other",\n  "confidence": 0.0-1.0,\n  "subtypes": ["subtype1", "subtype2"],\n  "extracted_fields": {{"field_name": "value", ...}}\n}}"""

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
            await _emit_audit(
                event=f"{self.audit_event_prefix}.capability_denied",
                processor=self.name,
                params={},
                error=str(exc),
            )
            return False


class FrancotypingResult(BaseModel):
    """Результат франкотипирования текста."""

    language: str = Field(description="ISO 639-1 language code")
    region: str | None = Field(default=None, description="Region/dialect code")
    script: str = Field(description="Latin|Cyrillic|Arabic|Han|etc.")
    classification: str = Field(description="top-level classification")
    confidence: float = Field(ge=0.0, le=1.0)


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
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, raises exceptions для error handling pipeline."""
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
        exchange.in_message.set_body(
            {
                "language": result.language,
                "region": result.region,
                "script": result.script,
                "classification": result.classification,
                "confidence": result.confidence,
            }
        )
        exchange.set_property("francotype_lang", result.language)
        exchange.set_property("francotype_script", result.script)

    def _build_prompt(self, text: str) -> str:
        truncated = text[:5000] if len(text) > 5000 else text
        return f'Analyze this text for language, region, and script classification.\n\nText:\n{truncated}\n\nRespond with JSON:\n{{\n  "language": "ISO 639-1 code (e.g., ru, en, fr, de)",\n  "region": "region code or null (e.g., RU, US, GB)",\n  "script": "Latin|Cyrillic|Arabic|Han|Hebrew|Greek|Armenian|Japanese|Korean|Thai",\n  "classification": "top-level category",\n  "confidence": 0.0-1.0\n}}'

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
            await _emit_audit(
                event=f"{self.audit_event_prefix}.capability_denied",
                processor=self.name,
                params={},
                error=str(exc),
            )
            return False


class TransactionCategorizerProcessor(BaseProcessor):
    """Категоризация транзакций (MCC + subcategory + merchant normalization)."""

    def __init__(self, taxonomy: str = "mcc") -> None:
        super().__init__(name=f"tx_cat:{taxonomy}")
        self.taxonomy = taxonomy

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, raises exceptions для error handling pipeline."""
        exchange.set_property("tx_taxonomy", self.taxonomy)
        exchange.set_property("banking_action", "ai.tx.categorize")

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализовать конфигурацию процессора в dict (для YAML/JSON spec). Returns None для non-serializable state."""
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
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, raises exceptions для error handling pipeline."""
        exchange.set_property("findoc_type", self.doc_type)
        exchange.set_property("banking_action", "ai.findoc.ocr_and_extract")

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализовать конфигурацию процессора в dict (для YAML/JSON spec). Returns None для non-serializable state."""
        spec: dict[str, Any] = {}
        if self.doc_type != "invoice":
            spec["doc_type"] = self.doc_type
        return {"findoc_ocr_llm": spec}
