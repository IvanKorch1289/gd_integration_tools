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

from src.backend.dsl.engine.processors import AgentGraphProcessor, MCPToolProcessor

if TYPE_CHECKING:
    from src.backend.dsl.builder import RouteBuilder


class AILlMMixin:
    """Поведенческий миксин AI / LLM для ``RouteBuilder``.

    Stateless: использует ``self._add`` / ``self._add_lazy`` через MRO.
    """

    __slots__ = ()

    # --- AI / LLM methods (S51 W1 extraction) ---

    def mcp_tool(
        self, uri: str, tool: str, *, result_property: str = "mcp_result"
    ) -> RouteBuilder:
        """Вызов внешнего MCP tool."""
        return self._add(  # type: ignore[attr-defined]
            MCPToolProcessor(
                tool_uri=uri, tool_name=tool, result_property=result_property
            )
        )

    def agent_graph(self, graph_name: str, tools: list[str]) -> RouteBuilder:
        """Запуск LangGraph-агента."""
        return self._add(  # type: ignore[attr-defined]
            AgentGraphProcessor(graph_name=graph_name, tools=tools)
        )

    def scrape(
        self,
        url: str | None = None,
        *,
        selectors: dict[str, str] | None = None,
        output_property: str = "scraped",
    ) -> RouteBuilder:
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
    ) -> RouteBuilder:
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
    ) -> RouteBuilder:
        """Прозрачный API proxy с request/response трансформацией."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.scraping",
            "ApiProxyProcessor",
            base_url=base_url,
            method=method,
            path=path,
            timeout=timeout,
        )

    def rag_search(
        self,
        query_field: str = "question",
        top_k: int = 5,
        namespace: str | None = None,
    ) -> RouteBuilder:
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
    ) -> RouteBuilder:
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
    ) -> RouteBuilder:
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
    ) -> RouteBuilder:
        """Построение промпта из шаблона + контекста из properties."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors",
            "PromptComposerProcessor",
            template=template,
            context_property=context_property,
        )

    def call_llm(
        self, provider: str | None = None, model: str | None = None
    ) -> RouteBuilder:
        """LLM chat-completion через ai_agent сервис (с PII-маскировкой)."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors",
            "LLMCallProcessor",
            provider=provider,
            model=model,
        )

    def parse_llm_output(self, schema: type | None = None) -> RouteBuilder:
        """Парсинг LLM-ответа в Pydantic-модель (с попыткой извлечь JSON)."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors", "LLMParserProcessor", schema=schema
        )

    def token_budget(self, max_tokens: int = 4096) -> RouteBuilder:
        """Ограничение по токенам (tiktoken) — обрезка текста до лимита."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors",
            "TokenBudgetProcessor",
            max_tokens=max_tokens,
        )

    def sanitize_pii(self) -> RouteBuilder:
        """Маскирование PII (email/phone/СНИЛС/карт) перед LLM."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors", "SanitizePIIProcessor"
        )

    def restore_pii(self) -> RouteBuilder:
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
    ) -> RouteBuilder:
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

    def publish_event(self, channel: str) -> RouteBuilder:
        """Публикация события через EventBus."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors",
            "EventPublishProcessor",
            channel=channel,
        )

    def load_memory(self, session_id_header: str = "X-Session-Id") -> RouteBuilder:
        """Загрузка conversation/facts из AgentMemory (Redis)."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors",
            "MemoryLoadProcessor",
            session_id_header=session_id_header,
        )

    def save_memory(self) -> RouteBuilder:
        """Сохранение результата в AgentMemory."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors", "MemorySaveProcessor"
        )

    def llm_fallback(
        self,
        *,
        models: list[str] | None = None,
        fallback_strategy: str = "sequential",
        max_retries: int = 2,
        result_property: str = "llm_result",
    ) -> RouteBuilder:
        """LLM call with automatic fallback across models.

        Args:
            models: Ordered list of model identifiers to try.
            fallback_strategy: ``"sequential"`` (try in order) or ``"parallel"`` (fastest wins).
            max_retries: Max retries per model.
            result_property: Property name for LLM response.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.ai.llmfallback_processor",
            "LLMFallbackProcessor",
            models=models,
            fallback_strategy=fallback_strategy,
            max_retries=max_retries,
            result_property=result_property,
        )

    def rerank(
        self,
        *,
        query_from: str = "body.query",
        documents_from: str = "body.documents",
        top_k: int = 5,
        result_property: str = "body.reranked_documents",
    ) -> RouteBuilder:
        """Rerank documents by relevance to query.

        Args:
            query_from: dotted-path to query string.
            documents_from: dotted-path to list of documents.
            top_k: Number of top documents to return.
            result_property: Property name for reranked results.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.ai.reranker",
            "RerankerProcessor",
            query_from=query_from,
            documents_from=documents_from,
            top_k=top_k,
            result_property=result_property,
        )
