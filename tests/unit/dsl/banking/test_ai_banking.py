"""Sprint 6 — Banking processors unit-тесты (AI-блок 7/12).

Покрывает 7 thin-wrapper процессоров из
:mod:`src.backend.dsl.engine.processors.ai_banking`:

* :class:`KycAmlVerifyProcessor`
* :class:`AntiFraudScoreProcessor`
* :class:`CreditScoringRagProcessor`
* :class:`CustomerChatbotProcessor`
* :class:`AppealProcessorAI`
* :class:`TransactionCategorizerProcessor`
* :class:`FinDocOcrLlmProcessor`

Тесты проверяют:

1. Конструктор по умолчанию: имя ``processor.name`` и значения параметров.
2. Кастомные значения параметров корректно сохраняются.
3. ``process()`` записывает ожидаемые ``exchange.properties`` (включая
   общий ключ ``banking_action`` для всех 7 процессоров).
4. ``to_spec()`` совместим с round-trip: значение по умолчанию опускается,
   кастомное — попадает в spec.

PLAN.md V16.1 §3 Sprint 6 DSL/Workflow row: «Banking-процессоры unit-тесты
(12 шт.)» — этот файл закрывает 7 шт. (AI-блок); RPA-блок 5 шт. — в
``test_rpa_banking.py``.
"""

# ruff: noqa: S101

from __future__ import annotations

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.ai_banking import (
    AntiFraudScoreProcessor,
    AppealProcessorAI,
    CreditScoringRagProcessor,
    CustomerChatbotProcessor,
    FinDocOcrLlmProcessor,
    KycAmlVerifyProcessor,
    TransactionCategorizerProcessor,
)


@pytest.fixture
def exchange() -> Exchange:
    """Минимальный Exchange — body не важен для thin-wrapper'ов."""
    return Exchange(in_message=Message(body={}, headers={}))


@pytest.fixture
def context() -> ExecutionContext:
    """Дефолтный контекст — action_registry уже выставлен."""
    return ExecutionContext()


# ────────────────────────── KycAmlVerifyProcessor ──────────────────────────


class TestKycAmlVerifyProcessor:
    def test_default_init_uses_ru_jurisdiction(self) -> None:
        proc = KycAmlVerifyProcessor()
        assert proc.jurisdiction == "ru"
        assert proc.name == "kyc_aml:ru"

    def test_custom_jurisdiction_in_name(self) -> None:
        proc = KycAmlVerifyProcessor(jurisdiction="kz")
        assert proc.jurisdiction == "kz"
        assert proc.name == "kyc_aml:kz"

    async def test_process_sets_action_and_jurisdiction_properties(
        self, exchange: Exchange, context: ExecutionContext
    ) -> None:
        proc = KycAmlVerifyProcessor(jurisdiction="by")
        await proc.process(exchange, context)
        assert exchange.properties["kyc_jurisdiction"] == "by"
        assert exchange.properties["banking_action"] == "ai.kyc_aml.verify"

    def test_to_spec_omits_default_jurisdiction(self) -> None:
        proc = KycAmlVerifyProcessor()
        assert proc.to_spec() == {"kyc_aml_verify": {}}

    def test_to_spec_includes_custom_jurisdiction(self) -> None:
        proc = KycAmlVerifyProcessor(jurisdiction="kz")
        assert proc.to_spec() == {"kyc_aml_verify": {"jurisdiction": "kz"}}


# ────────────────────────── AntiFraudScoreProcessor ────────────────────────


class TestAntiFraudScoreProcessor:
    def test_default_init_uses_default_model(self) -> None:
        proc = AntiFraudScoreProcessor()
        assert proc.model == "default"
        assert proc.name == "antifraud_llm:default"

    def test_custom_model_in_name(self) -> None:
        proc = AntiFraudScoreProcessor(model="gpt-4")
        assert proc.model == "gpt-4"
        assert proc.name == "antifraud_llm:gpt-4"

    async def test_process_sets_model_and_action(
        self, exchange: Exchange, context: ExecutionContext
    ) -> None:
        proc = AntiFraudScoreProcessor(model="claude-3.5")
        await proc.process(exchange, context)
        assert exchange.properties["antifraud_model"] == "claude-3.5"
        assert exchange.properties["banking_action"] == "ai.antifraud.score"

    def test_to_spec_omits_default_model(self) -> None:
        assert AntiFraudScoreProcessor().to_spec() == {"antifraud_score": {}}

    def test_to_spec_includes_custom_model(self) -> None:
        spec = AntiFraudScoreProcessor(model="gpt-4o").to_spec()
        assert spec == {"antifraud_score": {"model": "gpt-4o"}}


# ────────────────────────── CreditScoringRagProcessor ──────────────────────


class TestCreditScoringRagProcessor:
    def test_default_init_uses_retail_product(self) -> None:
        proc = CreditScoringRagProcessor()
        assert proc.product == "retail"
        assert proc.name == "credit_rag:retail"

    def test_custom_product_in_name(self) -> None:
        proc = CreditScoringRagProcessor(product="sme")
        assert proc.product == "sme"
        assert proc.name == "credit_rag:sme"

    async def test_process_sets_product_and_action(
        self, exchange: Exchange, context: ExecutionContext
    ) -> None:
        proc = CreditScoringRagProcessor(product="corporate")
        await proc.process(exchange, context)
        assert exchange.properties["credit_product"] == "corporate"
        assert exchange.properties["banking_action"] == "ai.credit.score_rag"

    def test_to_spec_omits_default_product(self) -> None:
        assert CreditScoringRagProcessor().to_spec() == {"credit_scoring_rag": {}}

    def test_to_spec_includes_custom_product(self) -> None:
        spec = CreditScoringRagProcessor(product="mortgage").to_spec()
        assert spec == {"credit_scoring_rag": {"product": "mortgage"}}


# ────────────────────────── CustomerChatbotProcessor ───────────────────────


class TestCustomerChatbotProcessor:
    def test_default_init_uses_web_channel(self) -> None:
        proc = CustomerChatbotProcessor()
        assert proc.channel == "web"
        assert proc.name == "chatbot:web"

    def test_custom_channel_in_name(self) -> None:
        proc = CustomerChatbotProcessor(channel="telegram")
        assert proc.channel == "telegram"
        assert proc.name == "chatbot:telegram"

    async def test_process_sets_channel_and_action(
        self, exchange: Exchange, context: ExecutionContext
    ) -> None:
        proc = CustomerChatbotProcessor(channel="whatsapp")
        await proc.process(exchange, context)
        assert exchange.properties["chatbot_channel"] == "whatsapp"
        assert exchange.properties["banking_action"] == "ai.chatbot.respond"

    def test_to_spec_omits_default_channel(self) -> None:
        assert CustomerChatbotProcessor().to_spec() == {"customer_chatbot": {}}

    def test_to_spec_includes_custom_channel(self) -> None:
        spec = CustomerChatbotProcessor(channel="telegram").to_spec()
        assert spec == {"customer_chatbot": {"channel": "telegram"}}


# ────────────────────────── AppealProcessorAI ──────────────────────────────


class TestAppealProcessorAI:
    def test_default_name(self) -> None:
        proc = AppealProcessorAI()
        assert proc.name == "appeal_ai"

    async def test_process_sets_only_action(
        self, exchange: Exchange, context: ExecutionContext
    ) -> None:
        proc = AppealProcessorAI()
        await proc.process(exchange, context)
        assert exchange.properties["banking_action"] == "ai.appeals.process"
        # У этого процессора нет параметра — кроме action ничего не пишется.
        assert "appeal_param" not in exchange.properties

    def test_to_spec_returns_empty_kwargs(self) -> None:
        assert AppealProcessorAI().to_spec() == {"appeal_ai": {}}


# ────────────────────────── TransactionCategorizerProcessor ────────────────


class TestTransactionCategorizerProcessor:
    def test_default_init_uses_mcc_taxonomy(self) -> None:
        proc = TransactionCategorizerProcessor()
        assert proc.taxonomy == "mcc"
        assert proc.name == "tx_cat:mcc"

    def test_custom_taxonomy_in_name(self) -> None:
        proc = TransactionCategorizerProcessor(taxonomy="merchant")
        assert proc.taxonomy == "merchant"
        assert proc.name == "tx_cat:merchant"

    async def test_process_sets_taxonomy_and_action(
        self, exchange: Exchange, context: ExecutionContext
    ) -> None:
        proc = TransactionCategorizerProcessor(taxonomy="custom_v2")
        await proc.process(exchange, context)
        assert exchange.properties["tx_taxonomy"] == "custom_v2"
        assert exchange.properties["banking_action"] == "ai.tx.categorize"

    def test_to_spec_omits_default_taxonomy(self) -> None:
        assert TransactionCategorizerProcessor().to_spec() == {"tx_categorize": {}}

    def test_to_spec_includes_custom_taxonomy(self) -> None:
        spec = TransactionCategorizerProcessor(taxonomy="merchant").to_spec()
        assert spec == {"tx_categorize": {"taxonomy": "merchant"}}


# ────────────────────────── FinDocOcrLlmProcessor ──────────────────────────


class TestFinDocOcrLlmProcessor:
    def test_default_init_uses_invoice_doc_type(self) -> None:
        proc = FinDocOcrLlmProcessor()
        assert proc.doc_type == "invoice"
        assert proc.name == "findoc_ocr:invoice"

    def test_custom_doc_type_in_name(self) -> None:
        proc = FinDocOcrLlmProcessor(doc_type="contract")
        assert proc.doc_type == "contract"
        assert proc.name == "findoc_ocr:contract"

    async def test_process_sets_doc_type_and_action(
        self, exchange: Exchange, context: ExecutionContext
    ) -> None:
        proc = FinDocOcrLlmProcessor(doc_type="statement")
        await proc.process(exchange, context)
        assert exchange.properties["findoc_type"] == "statement"
        assert exchange.properties["banking_action"] == "ai.findoc.ocr_and_extract"

    def test_to_spec_omits_default_doc_type(self) -> None:
        assert FinDocOcrLlmProcessor().to_spec() == {"findoc_ocr_llm": {}}

    def test_to_spec_includes_custom_doc_type(self) -> None:
        spec = FinDocOcrLlmProcessor(doc_type="contract").to_spec()
        assert spec == {"findoc_ocr_llm": {"doc_type": "contract"}}


# ────────────────────────── shared invariants ──────────────────────────────


@pytest.mark.parametrize(
    "proc_factory,expected_action",
    [
        (lambda: KycAmlVerifyProcessor(), "ai.kyc_aml.verify"),
        (lambda: AntiFraudScoreProcessor(), "ai.antifraud.score"),
        (lambda: CreditScoringRagProcessor(), "ai.credit.score_rag"),
        (lambda: CustomerChatbotProcessor(), "ai.chatbot.respond"),
        (lambda: AppealProcessorAI(), "ai.appeals.process"),
        (lambda: TransactionCategorizerProcessor(), "ai.tx.categorize"),
        (lambda: FinDocOcrLlmProcessor(), "ai.findoc.ocr_and_extract"),
    ],
)
async def test_all_ai_banking_processors_set_banking_action(
    proc_factory, expected_action: str, exchange: Exchange, context: ExecutionContext
) -> None:
    """Все 7 AI-banking процессоров обязаны записать ``banking_action``.

    Это инвариант для downstream-процессоров (audit/observability), которые
    разбирают `exchange.properties["banking_action"]` для классификации
    события и применения domain-специфичных policy.
    """
    proc = proc_factory()
    await proc.process(exchange, context)
    assert exchange.properties.get("banking_action") == expected_action


@pytest.mark.parametrize(
    "proc_factory,spec_key",
    [
        (lambda: KycAmlVerifyProcessor(), "kyc_aml_verify"),
        (lambda: AntiFraudScoreProcessor(), "antifraud_score"),
        (lambda: CreditScoringRagProcessor(), "credit_scoring_rag"),
        (lambda: CustomerChatbotProcessor(), "customer_chatbot"),
        (lambda: AppealProcessorAI(), "appeal_ai"),
        (lambda: TransactionCategorizerProcessor(), "tx_categorize"),
        (lambda: FinDocOcrLlmProcessor(), "findoc_ocr_llm"),
    ],
)
def test_all_ai_banking_processors_to_spec_returns_single_key_dict(
    proc_factory, spec_key: str
) -> None:
    """Каждый процессор сериализуется как ``{spec_key: {...}}`` — round-trip контракт."""
    spec = proc_factory().to_spec()
    assert spec is not None
    assert list(spec.keys()) == [spec_key]
    assert isinstance(spec[spec_key], dict)
