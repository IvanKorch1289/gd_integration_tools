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

from typing import TYPE_CHECKING, Any, Callable

from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors import AgentGraphProcessor, MCPToolProcessor

if TYPE_CHECKING:
    from src.backend.dsl.builder import RouteBuilder


class AIRPAMixin:
    """Поведенческий миксин AI / RPA / Banking-AI для ``RouteBuilder``.

    Stateless: миксин использует ``self._add`` / ``self._add_lazy`` через
    MRO; собственных полей не содержит. Контракт см. в ``base.py``.
    """

    __slots__ = ()

    # ── Integration processors (MCP / Agent) ──

    def mcp_tool(
        self, uri: str, tool: str, *, result_property: str = "mcp_result"
    ) -> "RouteBuilder":
        """Вызов внешнего MCP tool."""
        return self._add(  # type: ignore[attr-defined]
            MCPToolProcessor(
                tool_uri=uri, tool_name=tool, result_property=result_property
            )
        )

    def agent_graph(self, graph_name: str, tools: list[str]) -> "RouteBuilder":
        """Запуск LangGraph-агента."""
        return self._add(  # type: ignore[attr-defined]
            AgentGraphProcessor(graph_name=graph_name, tools=tools)
        )

    # ── Scraping Pipeline ──

    def scrape(
        self,
        url: str | None = None,
        *,
        selectors: dict[str, str] | None = None,
        output_property: str = "scraped",
    ) -> "RouteBuilder":
        """Извлечение данных с URL через CSS-селекторы (с SSRF-защитой)."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.scraping",
            "ScrapeProcessor",
            url=url,
            selectors=selectors,
            output_property=output_property,
        )

    def paginate(
        self,
        *,
        next_selector: str = "a.next",
        item_selector: str | None = None,
        max_pages: int = 10,
        start_url: str | None = None,
    ) -> "RouteBuilder":
        """Multi-page crawling с защитой от циклов и лимитом страниц."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.scraping",
            "PaginateProcessor",
            next_selector=next_selector,
            item_selector=item_selector,
            max_pages=max_pages,
            start_url=start_url,
        )

    def api_proxy(
        self,
        base_url: str,
        *,
        method: str = "GET",
        path: str = "",
        timeout: float = 30.0,
    ) -> "RouteBuilder":
        """Прозрачный API proxy с request/response трансформацией."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.scraping",
            "ApiProxyProcessor",
            base_url=base_url,
            method=method,
            path=path,
            timeout=timeout,
        )

    # ── AI Pipeline ──

    def rag_search(
        self,
        query_field: str = "question",
        top_k: int = 5,
        namespace: str | None = None,
    ) -> "RouteBuilder":
        """RAG vector search: top-K ближайших документов по семантике."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors",
            "VectorSearchProcessor",
            query_field=query_field,
            top_k=top_k,
            namespace=namespace,
        )

    def rag_query(
        self,
        *,
        query_field: str = "question",
        top_k: int = 5,
        namespace: str | None = None,
        strategy: str = "dense",
        max_staleness_hours: float | None = None,
        system_prompt: str = "",
        output_property: str = "augment_result",
    ) -> "RouteBuilder":
        """RAG query с выбором стратегии retrieval (S11 K3 W3).

        ``strategy`` ∈ ``{"dense", "hybrid", "hyde", "multi_query"}`` —
        прокидывается в exchange.property ``rag_strategy`` и в payload
        ``augment_result`` для downstream branch-logic. ``dense`` — стандартный
        k-NN; ``hybrid`` — lexical+semantic union; ``hyde`` — Hypothetical
        Document Embeddings; ``multi_query`` — n-генераций query.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors",
            "RagQueryProcessor",
            query_field=query_field,
            top_k=top_k,
            namespace=namespace,
            strategy=strategy,
            max_staleness_hours=max_staleness_hours,
            system_prompt=system_prompt,
            output_property=output_property,
        )

    def rag_ingest(
        self,
        *,
        collection: str = "default",
        source_property: str | None = None,
        modal: str = "text",
        output_property: str = "ingest_doc_id",
    ) -> "RouteBuilder":
        """RAG ingest: добавление документа из body/property в vector store (S11 K3 W2).

        ``modal`` хранится в metadata для downstream-консьюмеров
        мультимодального индекса (``text``/``image``/``audio``/``video``).
        Возвращённый ``doc_id`` сохраняется в ``output_property``.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors",
            "RagIngestProcessor",
            source_property=source_property,
            modal=modal,
            collection=collection,
            output_property=output_property,
        )

    def compose_prompt(
        self, template: str, context_property: str = "vector_results"
    ) -> "RouteBuilder":
        """Построение промпта из шаблона + контекста из properties."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors",
            "PromptComposerProcessor",
            template=template,
            context_property=context_property,
        )

    def call_llm(
        self, provider: str | None = None, model: str | None = None
    ) -> "RouteBuilder":
        """LLM chat-completion через ai_agent сервис (с PII-маскировкой)."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors",
            "LLMCallProcessor",
            provider=provider,
            model=model,
        )

    def parse_llm_output(self, schema: type | None = None) -> "RouteBuilder":
        """Парсинг LLM-ответа в Pydantic-модель (с попыткой извлечь JSON)."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors", "LLMParserProcessor", schema=schema
        )

    def token_budget(self, max_tokens: int = 4096) -> "RouteBuilder":
        """Ограничение по токенам (tiktoken) — обрезка текста до лимита."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors",
            "TokenBudgetProcessor",
            max_tokens=max_tokens,
        )

    def sanitize_pii(self) -> "RouteBuilder":
        """Маскирование PII (email/phone/СНИЛС/карт) перед LLM."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors", "SanitizePIIProcessor"
        )

    def restore_pii(self) -> "RouteBuilder":
        """Восстановление PII в ответе после LLM."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors", "RestorePIIProcessor"
        )

    def get_feedback_examples(
        self,
        *,
        query_from: str = "body.query",
        agent_id: str | None = None,
        positive_k: int = 3,
        negative_k: int = 2,
        min_similarity: float = 0.0,
        inject_as: str = "feedback_examples",
    ) -> "RouteBuilder":
        """Few-shot примеры из AI Feedback RAG.

        Инжектирует ``positive``/``negative`` примеры в properties
        под ключом ``inject_as``. Используется перед ``call_llm``
        для промптов с опорой на реальные размеченные ответы.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors",
            "GetFeedbackExamplesProcessor",
            query_from=query_from,
            agent_id=agent_id,
            positive_k=positive_k,
            negative_k=negative_k,
            min_similarity=min_similarity,
            inject_as=inject_as,
        )

    def publish_event(self, channel: str) -> "RouteBuilder":
        """Публикация события через EventBus."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors",
            "EventPublishProcessor",
            channel=channel,
        )

    def load_memory(self, session_id_header: str = "X-Session-Id") -> "RouteBuilder":
        """Загрузка conversation/facts из AgentMemory (Redis)."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors",
            "MemoryLoadProcessor",
            session_id_header=session_id_header,
        )

    def save_memory(self) -> "RouteBuilder":
        """Сохранение результата в AgentMemory."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors", "MemorySaveProcessor"
        )

    # ── Web Automation (RPA) ──

    def navigate(self, url: str) -> "RouteBuilder":
        """Открыть URL в браузере (Playwright)."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.web", "NavigateProcessor", url=url
        )

    def click(self, url: str, selector: str) -> "RouteBuilder":
        """Клик по CSS-селектору."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.web",
            "ClickProcessor",
            url=url,
            selector=selector,
        )

    def fill_form(
        self, url: str, fields: dict | None = None, submit: str | None = None
    ) -> "RouteBuilder":
        """Заполнение формы по полям + опциональный submit."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.web",
            "FillFormProcessor",
            url=url,
            fields=fields,
            submit=submit,
        )

    def extract(
        self, selector: str, url: str | None = None, output_property: str = "extracted"
    ) -> "RouteBuilder":
        """Извлечение текста по CSS-селектору."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.web",
            "ExtractProcessor",
            url=url,
            selector=selector,
            output_property=output_property,
        )

    def screenshot(self, url: str | None = None) -> "RouteBuilder":
        """Скриншот страницы как bytes."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.web", "ScreenshotProcessor", url=url
        )

    def run_scenario(self, steps: list[dict] | None = None) -> "RouteBuilder":
        """Multi-step web сценарий (navigate/click/fill/extract)."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.web", "RunScenarioProcessor", steps=steps
        )

    # ── AI Extended ──

    def call_llm_with_fallback(
        self, providers: list[str], *, model: str = "default"
    ) -> "RouteBuilder":
        """LLM с fallback-цепочкой провайдеров."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.ai",
            "LLMFallbackProcessor",
            providers=providers,
            model=model,
        )

    def cache(
        self, key_fn: Callable[[Exchange[Any]], str], *, ttl: int = 3600
    ) -> "RouteBuilder":
        """Redis-кеш: проверяет наличие по ключу, пропускает если есть."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.ai",
            "CacheProcessor",
            key_fn=key_fn,
            ttl_seconds=ttl,
        )

    def cache_write(
        self, key_fn: Callable[[Exchange[Any]], str], *, ttl: int = 3600
    ) -> "RouteBuilder":
        """Redis-кеш: записывает результат после обработки."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.ai",
            "CacheWriteProcessor",
            key_fn=key_fn,
            ttl_seconds=ttl,
        )

    def guardrails(
        self,
        *,
        max_length: int = 10000,
        blocked_patterns: list[str] | None = None,
        required_fields: list[str] | None = None,
    ) -> "RouteBuilder":
        """Проверка LLM output на безопасность (длина, blocklist, required fields)."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.ai",
            "GuardrailsProcessor",
            max_length=max_length,
            blocked_patterns=blocked_patterns,
            required_fields=required_fields,
        )

    def semantic_route(
        self,
        intents: dict[str, str],
        *,
        default_route: str | None = None,
        query_field: str = "question",
        threshold: float = 0.5,
        namespace: str = "intents",
    ) -> "RouteBuilder":
        """Semantic routing — RAG-based intent detection → выбор маршрута."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.ai",
            "SemanticRouterProcessor",
            intents=intents,
            default_route=default_route,
            query_field=query_field,
            threshold=threshold,
            namespace=namespace,
        )

    # ── RPA terminal / desktop / mobile ──

    def citrix(self, operation: str, session_id: str) -> "RouteBuilder":
        """Citrix/RDP-сессия (launch/click/type/screenshot/close)."""
        from src.backend.dsl.engine.processors.rpa_banking import CitrixSessionProcessor

        return self._add(  # type: ignore[attr-defined]
            CitrixSessionProcessor(operation=operation, session_id=session_id)
        )

    def terminal_3270(
        self, host: str, port: int = 23, action: str = "query"
    ) -> "RouteBuilder":
        """IBM 3270 терминал-эмулятор (мейнфрейм)."""
        from src.backend.dsl.engine.processors.rpa_banking import (
            TerminalEmulator3270Processor,
        )

        return self._add(  # type: ignore[attr-defined]
            TerminalEmulator3270Processor(host=host, port=port, action=action)
        )

    def appium_mobile(
        self, platform: str, app_package: str, operation: str
    ) -> "RouteBuilder":
        """Appium автоматизация мобильных приложений (android/ios)."""
        from src.backend.dsl.engine.processors.rpa_banking import AppiumMobileProcessor

        return self._add(  # type: ignore[attr-defined]
            AppiumMobileProcessor(
                platform=platform, app_package=app_package, operation=operation
            )
        )

    def email_driven(
        self,
        mailbox: str = "INBOX",
        subject_filter: str | None = None,
        extract: str = "body_table",
    ) -> "RouteBuilder":
        """IMAP → structured data pipeline."""
        from src.backend.dsl.engine.processors.rpa_banking import EmailDrivenProcessor

        return self._add(  # type: ignore[attr-defined]
            EmailDrivenProcessor(
                mailbox=mailbox, subject_filter=subject_filter, extract=extract
            )
        )

    def keystroke_replay(self, script_name: str) -> "RouteBuilder":
        """Воспроизведение записанного сценария клавиатуры/мыши."""
        from src.backend.dsl.engine.processors.rpa_banking import (
            KeystrokeReplayProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            KeystrokeReplayProcessor(script_name=script_name)
        )

    # ── Banking AI ──

    def kyc_aml_verify(self, jurisdiction: str = "ru") -> "RouteBuilder":
        """KYC/AML верификация клиента."""
        from src.backend.dsl.engine.processors.ai_banking import KycAmlVerifyProcessor

        return self._add(  # type: ignore[attr-defined]
            KycAmlVerifyProcessor(jurisdiction=jurisdiction)
        )

    def antifraud_score(self, model: str = "default") -> "RouteBuilder":
        """LLM-скоринг антифрода (поверх детерминистических правил)."""
        from src.backend.dsl.engine.processors.ai_banking import AntiFraudScoreProcessor

        return self._add(  # type: ignore[attr-defined]
            AntiFraudScoreProcessor(model=model)
        )

    def credit_scoring_rag(self, product: str = "retail") -> "RouteBuilder":
        """Кредитный скоринг через RAG."""
        from src.backend.dsl.engine.processors.ai_banking import (
            CreditScoringRagProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            CreditScoringRagProcessor(product=product)
        )

    def customer_chatbot(self, channel: str = "web") -> "RouteBuilder":
        """Клиентский чат-бот (tool-use: balance, statement, faq, escalate)."""
        from src.backend.dsl.engine.processors.ai_banking import (
            CustomerChatbotProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            CustomerChatbotProcessor(channel=channel)
        )

    def appeal_ai(self) -> "RouteBuilder":
        """Автоматическая обработка клиентских обращений."""
        from src.backend.dsl.engine.processors.ai_banking import AppealProcessorAI

        return self._add(AppealProcessorAI())  # type: ignore[attr-defined]

    def tx_categorize(self, taxonomy: str = "mcc") -> "RouteBuilder":
        """Категоризация транзакций (MCC + merchant normalization)."""
        from src.backend.dsl.engine.processors.ai_banking import (
            TransactionCategorizerProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            TransactionCategorizerProcessor(taxonomy=taxonomy)
        )

    def findoc_ocr_llm(self, doc_type: str = "invoice") -> "RouteBuilder":
        """OCR + LLM для финансовых документов."""
        from src.backend.dsl.engine.processors.ai_banking import FinDocOcrLlmProcessor

        return self._add(  # type: ignore[attr-defined]
            FinDocOcrLlmProcessor(doc_type=doc_type)
        )
