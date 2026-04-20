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

from app.dsl.engine.context import ExecutionContext
from app.dsl.engine.exchange import Exchange
from app.dsl.engine.processors.base import BaseProcessor

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


class CustomerChatbotProcessor(BaseProcessor):
    """Клиентский чат-бот (tool-use: balance, statement, faq, escalate)."""

    def __init__(self, channel: str = "web") -> None:
        super().__init__(name=f"chatbot:{channel}")
        self.channel = channel

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        exchange.set_property("chatbot_channel", self.channel)
        exchange.set_property("banking_action", "ai.chatbot.respond")


class AppealProcessorAI(BaseProcessor):
    """Автоматическая обработка клиентских обращений.

    Классификация (тема, срочность, эмоция) + черновик ответа +
    автоматическая маршрутизация в нужный отдел.
    """

    def __init__(self) -> None:
        super().__init__(name="appeal_ai")

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        exchange.set_property("banking_action", "ai.appeals.process")


class TransactionCategorizerProcessor(BaseProcessor):
    """Категоризация транзакций (MCC + subcategory + merchant normalization)."""

    def __init__(self, taxonomy: str = "mcc") -> None:
        super().__init__(name=f"tx_cat:{taxonomy}")
        self.taxonomy = taxonomy

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        exchange.set_property("tx_taxonomy", self.taxonomy)
        exchange.set_property("banking_action", "ai.tx.categorize")


class FinDocOcrLlmProcessor(BaseProcessor):
    """OCR + LLM для финансовых документов (счета, договоры, выписки)."""

    def __init__(self, doc_type: str = "invoice") -> None:
        super().__init__(name=f"findoc_ocr:{doc_type}")
        self.doc_type = doc_type

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        exchange.set_property("findoc_type", self.doc_type)
        exchange.set_property("banking_action", "ai.findoc.ocr_and_extract")
