"""AI-пайплайны для банковского домена.

Каждый процессор — thin wrapper над action'ом. Сами модели/промпты/RAG
живут в сервисах (`services/ai_*.py`, `services/rag_service.py`).

Процессоры:
- KYC/AML verification (документы → decision + score)
- Anti-fraud LLM scoring (транзакция → risk score + explanation)
- Credit scoring via RAG (клиент + история → решение + cited reasons)
- Customer chatbot (FAQ + баланс/выписка через tool-use)
- Appeal auto-processing (обращение → категория + приоритет + ответ)
- Transaction categorization (tx → категория MCC + subcategory)
- Financial document OCR+LLM (PDF → структура + валидация)
"""

from __future__ import annotations

from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

__all__ = (
    "KycAmlVerifyProcessor",
    "AntiFraudScoreProcessor",
    "CreditScoringRagProcessor",
    "CustomerChatbotProcessor",
    "AppealProcessorAI",
    "TransactionCategorizerProcessor",
    "FinDocOcrLlmProcessor",
)


class KycAmlVerifyProcessor(BaseProcessor):
    """KYC/AML верификация клиента.

    Вход: {"documents": [...], "customer": {...}}.
    Выход: {"decision": "approve"|"review"|"reject", "score": float, "reasons": [...]}
    """

    def __init__(self, jurisdiction: str = "ru") -> None:
        super().__init__(name=f"kyc_aml:{jurisdiction}")
        self.jurisdiction = jurisdiction

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        exchange.set_property("kyc_jurisdiction", self.jurisdiction)
        exchange.set_property("banking_action", "ai.kyc_aml.verify")

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {}
        if self.jurisdiction != "ru":
            spec["jurisdiction"] = self.jurisdiction
        return {"kyc_aml_verify": spec}


class AntiFraudScoreProcessor(BaseProcessor):
    """LLM-скоринг антифрода поверх детерминистических правил.

    Детерминистические правила живут в `core.security.banking.AntiFraudEngine`;
    этот процессор добавляет LLM-layer для граничных случаев (review).
    """

    def __init__(self, model: str = "default") -> None:
        super().__init__(name=f"antifraud_llm:{model}")
        self.model = model

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        exchange.set_property("antifraud_model", self.model)
        exchange.set_property("banking_action", "ai.antifraud.score")

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {}
        if self.model != "default":
            spec["model"] = self.model
        return {"antifraud_score": spec}


class CreditScoringRagProcessor(BaseProcessor):
    """Кредитный скоринг через RAG: клиент + история + policy-документы.

    Вход: {"customer": {...}, "amount": ..., "product": "..."}.
    Выход: {"approved": bool, "limit": ..., "rate": ..., "citations": [...]}.
    """

    def __init__(self, product: str = "retail") -> None:
        super().__init__(name=f"credit_rag:{product}")
        self.product = product

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        exchange.set_property("credit_product", self.product)
        exchange.set_property("banking_action", "ai.credit.score_rag")

    def to_spec(self) -> dict[str, Any] | None:
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
        exchange.set_property("chatbot_channel", self.channel)
        exchange.set_property("banking_action", "ai.chatbot.respond")

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {}
        if self.channel != "web":
            spec["channel"] = self.channel
        return {"customer_chatbot": spec}


class AppealProcessorAI(BaseProcessor):
    """Автоматическая обработка клиентских обращений.

    Классификация (тема, срочность, эмоция) + черновик ответа +
    автоматическая маршрутизация в нужный отдел.
    """

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
