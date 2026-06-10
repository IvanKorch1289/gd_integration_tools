"""AI / RPA / Banking-AI миксин для RouteBuilder.

Группа: call_llm / call_llm_with_fallback / cache / cache_write /
guardrails / semantic_route / mcp_tool / agent_graph / rag_search /
compose_prompt / parse_llm_output / token_budget / sanitize_pii /
restore_pii / get_feedback_examples / publish_event / load_memory /
save_memory; banking AI (kyc_aml_verify / antifraud_score /
credit_scoring_rag / customer_chatbot / appeal_ai / tx_categorize /
findoc_ocr_llm); RPA (navigate / click / fill_form / extract /
screenshot / run_scenario / citrix / terminal_3270 / appium_mobile /
email_driven / keystroke_replay / scrape / paginate / api_proxy).

Stateless — см. контракт в ``base.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.dsl.builder import RouteBuilder





class BankingScriptsMixin:
    """banking AI + script execution (kyc_aml / antifraud / credit / customer / appeal / tx / findoc + script_* методы) для ``RouteBuilder``. S52 W1 extraction."""

    __slots__ = ()

    # --- banking AI + scripting (kyc_aml, antifraud, credit scoring, customer chatbot, appeal, tx categorize, findoc OCR, script execution) ---

    def kyc_aml_verify(self, jurisdiction: str = "ru") -> RouteBuilder:
        """KYC/AML верификация клиента."""
        from src.backend.dsl.engine.processors.ai_banking import KycAmlVerifyProcessor

        return self._add(  # type: ignore[attr-defined]
            KycAmlVerifyProcessor(jurisdiction=jurisdiction)
        )



    def antifraud_score(self, model: str = "default") -> RouteBuilder:
        """LLM-скоринг антифрода (поверх детерминистических правил)."""
        from src.backend.dsl.engine.processors.ai_banking import AntiFraudScoreProcessor

        return self._add(  # type: ignore[attr-defined]
            AntiFraudScoreProcessor(model=model)
        )



    def credit_scoring_rag(self, product: str = "retail") -> RouteBuilder:
        """Кредитный скоринг через RAG."""
        from src.backend.dsl.engine.processors.ai_banking import (
            CreditScoringRagProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            CreditScoringRagProcessor(product=product)
        )



    def customer_chatbot(self, channel: str = "web") -> RouteBuilder:
        """Клиентский чат-бот (tool-use: balance, statement, faq, escalate)."""
        from src.backend.dsl.engine.processors.ai_banking import (
            CustomerChatbotProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            CustomerChatbotProcessor(channel=channel)
        )



    def appeal_ai(self) -> RouteBuilder:
        """Автоматическая обработка клиентских обращений."""
        from src.backend.dsl.engine.processors.ai_banking import AppealProcessorAI

        return self._add(AppealProcessorAI())  # type: ignore[attr-defined]



    def tx_categorize(self, taxonomy: str = "mcc") -> RouteBuilder:
        """Категоризация транзакций (MCC + merchant normalization)."""
        from src.backend.dsl.engine.processors.ai_banking import (
            TransactionCategorizerProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            TransactionCategorizerProcessor(taxonomy=taxonomy)
        )



    def findoc_ocr_llm(self, doc_type: str = "invoice") -> RouteBuilder:
        """OCR + LLM для финансовых документов."""
        from src.backend.dsl.engine.processors.ai_banking import FinDocOcrLlmProcessor

        return self._add(  # type: ignore[attr-defined]
            FinDocOcrLlmProcessor(doc_type=doc_type)
        )



    def script_python(
        self,
        code: str,
        *,
        timeout_seconds: float = 30.0,
        env: dict[str, str] | None = None,
        allowed_languages: list[str] | None = None,
    ) -> RouteBuilder:
        """Выполнить inline Python-код через текущий интерпретатор.

        Результат пишется в exchange body как
        ``{"stdout", "stderr", "exit_code", "language"}``.
        """
        from src.backend.dsl.engine.processors.script_runner import (
            ScriptRunnerProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            ScriptRunnerProcessor(
                language="python",
                code=code,
                timeout_seconds=timeout_seconds,
                env=env,
                allowed_languages=allowed_languages,
            )
        )



    def script_node(
        self,
        code: str,
        *,
        timeout_seconds: float = 30.0,
        env: dict[str, str] | None = None,
        allowed_languages: list[str] | None = None,
    ) -> RouteBuilder:
        """Выполнить inline Node.js-код (требует ``node`` в PATH)."""
        from src.backend.dsl.engine.processors.script_runner import (
            ScriptRunnerProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            ScriptRunnerProcessor(
                language="node",
                code=code,
                timeout_seconds=timeout_seconds,
                env=env,
                allowed_languages=allowed_languages,
            )
        )



    def script_ruby(
        self,
        code: str,
        *,
        timeout_seconds: float = 30.0,
        env: dict[str, str] | None = None,
        allowed_languages: list[str] | None = None,
    ) -> RouteBuilder:
        """Выполнить inline Ruby-код (требует ``ruby`` в PATH)."""
        from src.backend.dsl.engine.processors.script_runner import (
            ScriptRunnerProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            ScriptRunnerProcessor(
                language="ruby",
                code=code,
                timeout_seconds=timeout_seconds,
                env=env,
                allowed_languages=allowed_languages,
            )
        )



    def script_shell(
        self,
        code: str,
        *,
        timeout_seconds: float = 30.0,
        env: dict[str, str] | None = None,
        allowed_languages: list[str] | None = None,
    ) -> RouteBuilder:
        """Выполнить shell-скрипт через ``/bin/sh`` (whitelist рекомендуется)."""
        from src.backend.dsl.engine.processors.script_runner import (
            ScriptRunnerProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            ScriptRunnerProcessor(
                language="shell",
                code=code,
                timeout_seconds=timeout_seconds,
                env=env,
                allowed_languages=allowed_languages,
            )
        )

