"""AI/ML DSL процессоры — LLM, RAG, PII, prompt composition."""

from typing import Any, Callable

import orjson

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

__all__ = (
    "PromptComposerProcessor",
    "LLMCallProcessor",
    "LLMParserProcessor",
    "TokenBudgetProcessor",
    "VectorSearchProcessor",
    "RagQueryProcessor",
    "RagPIIRedactionProcessor",
    "SanitizePIIProcessor",
    "RestorePIIProcessor",
    "LLMFallbackProcessor",
    "CacheProcessor",
    "CacheWriteProcessor",
    "GuardrailsProcessor",
    "SemanticRouterProcessor",
    "GetFeedbackExamplesProcessor",
)


class PromptComposerProcessor(BaseProcessor):
    """Строит промпт из шаблона + контекст из exchange properties."""

    def __init__(
        self,
        template: str,
        context_property: str = "vector_results",
        output_property: str = "_composed_prompt",
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        self._template = template
        self._context_property = context_property
        self._output_property = output_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        ctx_data = exchange.properties.get(self._context_property, "")
        if isinstance(ctx_data, list):
            ctx_data = "\n---\n".join(
                item.get("document", str(item)) if isinstance(item, dict) else str(item)
                for item in ctx_data
            )
        body = exchange.in_message.body
        if isinstance(body, dict):
            variables = {**body, "context": ctx_data}
        else:
            variables = {"input": body, "context": ctx_data}
        try:
            prompt = self._template.format(**variables)
        except KeyError:
            prompt = self._template.format_map(
                {**variables, **{k: "" for k in self._template.split("{") if "}" in k}}
            )
        exchange.set_property(self._output_property, prompt)

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {"template": self._template}
        if self._context_property != "vector_results":
            spec["context_property"] = self._context_property
        return {"compose_prompt": spec}


class LLMCallProcessor(BaseProcessor):
    """Вызывает LLM с retry, rate-limit detection и cost tracking.

    Сохраняет в properties:
    - llm.provider — фактически использованный провайдер
    - llm.model — модель
    - llm.tokens_used — количество токенов (если LLM вернул usage)
    - llm.cost_usd — оценка стоимости (если есть таблица цен в config)

    Args:
        max_retries: Количество повторов при transient ошибках (default 2).
        retry_delay: Базовая задержка между retry (сек).
    """

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        prompt_property: str = "_composed_prompt",
        max_retries: int = 2,
        retry_delay: float = 1.0,
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        self._provider = provider
        self._model = model
        self._prompt_property = prompt_property
        self._max_retries = max_retries
        self._retry_delay = retry_delay

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        import logging

        from src.backend.infrastructure.resilience.retry import make_async_retry

        prompt = exchange.properties.get(self._prompt_property)
        if prompt is None:
            prompt = (
                exchange.in_message.body
                if isinstance(exchange.in_message.body, str)
                else str(exchange.in_message.body)
            )

        # S30 w4: сохраняем prompt для NeMo output guardrails
        exchange.set_property("llm.original_prompt", prompt)

        _log = logging.getLogger("dsl.ai")

        try:
            from src.backend.services.ai.ai_agent import get_ai_agent_service
        except ImportError as exc:
            exchange.fail(f"AI agent service unavailable: {exc}")
            return

        agent = get_ai_agent_service()

        # K3 W1: замена custom retry-loop на tenacity через make_async_retry.
        # Rate-limit (RuntimeError с "rate"/"429"/"quota") — non-retryable,
        # обрабатывается отдельно до вызова retry-обёртки.
        _retryable = (TimeoutError, ConnectionError)

        @make_async_retry(
            max_attempts=self._max_retries + 1,
            initial_backoff=self._retry_delay,
            multiplier=2.0,
            on=_retryable,
        )
        async def _chat_with_retry() -> Any:
            """Выполняет один LLM-запрос; tenacity перехватывает transient ошибки."""
            try:
                return await agent.chat(
                    messages=[{"role": "user", "content": prompt}],
                    provider=self._provider,
                    model=self._model or "default",
                )
            except RuntimeError as exc:
                msg = str(exc).lower()
                if "rate" in msg or "429" in msg or "quota" in msg:
                    # Rate-limit — non-retryable, пробрасываем как есть.
                    raise
                # Остальные RuntimeError считаем transient — оборачиваем
                # в ConnectionError, чтобы tenacity их поймал.
                raise ConnectionError(str(exc)) from exc

        try:
            result = await _chat_with_retry()
        except RuntimeError as exc:
            # rate-limit или другие non-retryable RuntimeError
            exchange.fail(f"LLM rate limit: {exc}")
            return
        except (TimeoutError, ConnectionError) as exc:
            exchange.fail(
                f"LLM call failed after {self._max_retries + 1} attempts: {exc}"
            )
            return

        if isinstance(result, dict):
            usage = result.get("usage") or {}
            tokens = int(usage.get("total_tokens", 0)) if usage else 0
            if tokens:
                exchange.set_property("llm.tokens_used", tokens)
                exchange.set_property("llm.cost_usd", round(tokens * 0.00002, 6))
            if "model" in result:
                exchange.set_property("llm.model", result["model"])

        exchange.set_property("llm.provider", self._provider or "fallback")
        exchange.in_message.set_body(result)

        _log.info(
            "llm_call_ok",
            extra={
                "provider": self._provider,
                "model": self._model,
                "tokens": exchange.properties.get("llm.tokens_used", 0),
            },
        )

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {}
        if self._provider is not None:
            spec["provider"] = self._provider
        if self._model is not None:
            spec["model"] = self._model
        return {"call_llm": spec}


class LLMParserProcessor(BaseProcessor):
    """Парсит ответ LLM в структурированный формат."""

    def __init__(
        self, schema: type | None = None, format: str = "json", name: str | None = None
    ) -> None:
        super().__init__(name)
        self._schema = schema
        self._format = format

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        if not isinstance(body, str):
            return
        text = body.strip()
        if self._format == "json":
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                text = text[start:end]
            try:
                parsed = orjson.loads(text)
            except (orjson.JSONDecodeError, ValueError):
                exchange.fail(f"LLM output is not valid JSON: {text[:100]}")
                return
        else:
            parsed = text
        if self._schema is not None:
            try:
                from pydantic import BaseModel

                if issubclass(self._schema, BaseModel):
                    parsed = self._schema.model_validate(parsed)
            except (ValueError, TypeError) as exc:
                exchange.fail(f"LLM output schema validation failed: {exc}")
                return
        exchange.in_message.set_body(parsed)


class TokenBudgetProcessor(BaseProcessor):
    """Обрезает текст по token budget (tiktoken для точного подсчёта)."""

    def __init__(
        self,
        max_tokens: int = 4096,
        source_property: str | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        self._max_tokens = max_tokens
        self._source_property = source_property
        self._encoder: Any = None

    def _get_encoder(self) -> Any:
        if self._encoder is None:
            try:
                import tiktoken

                self._encoder = tiktoken.encoding_for_model("gpt-4")
            except ImportError:
                return None
        return self._encoder

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        if self._source_property:
            text = exchange.properties.get(self._source_property, "")
        else:
            text = exchange.in_message.body
        if not isinstance(text, str):
            return

        encoder = self._get_encoder()
        if encoder is not None:
            tokens = encoder.encode(text)
            if len(tokens) > self._max_tokens:
                text = encoder.decode(tokens[: self._max_tokens]) + "\n...[truncated]"
        else:
            max_chars = self._max_tokens * 4
            if len(text) > max_chars:
                text = text[:max_chars] + "\n...[truncated]"

        if self._source_property:
            exchange.set_property(self._source_property, text)
        else:
            exchange.in_message.set_body(text)


class VectorSearchProcessor(BaseProcessor):
    """Ищет в RAG vector store, результаты в exchange properties."""

    def __init__(
        self,
        query_field: str = "question",
        top_k: int = 5,
        namespace: str | None = None,
        output_property: str = "vector_results",
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        self._query_field = query_field
        self._top_k = top_k
        self._namespace = namespace
        self._output_property = output_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        if isinstance(body, dict):
            query = body.get(self._query_field, "")
        else:
            query = str(body)
        if not query:
            exchange.set_property(self._output_property, [])
            return
        from src.backend.services.ai.rag_service import get_rag_service

        rag = get_rag_service()
        results = await rag.search(
            query=query, top_k=self._top_k, namespace=self._namespace
        )
        exchange.set_property(self._output_property, results)

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {}
        if self._query_field != "question":
            spec["query_field"] = self._query_field
        if self._top_k != 5:
            spec["top_k"] = self._top_k
        if self._namespace is not None:
            spec["namespace"] = self._namespace
        return {"rag_search": spec}


# Допустимые стратегии retrieval для :class:`RagQueryProcessor`.
# ``dense`` — стандартный k-NN; остальные обрабатываются downstream
# retriever'ом (см. RAG plan S11 K3) и активируются по namespace-config.
_RAG_STRATEGIES: tuple[str, ...] = (
    "dense",
    "hybrid",
    "hyde",
    "multi_query",
    "adaptive",
)


class RagQueryProcessor(BaseProcessor):
    """Structured RAG query с freshness-фильтрацией (Sprint 9 K4 W3).

    В отличие от :class:`VectorSearchProcessor` (raw vectors), возвращает
    :class:`AugmentResult` с метаданными по freshness и worst_freshness
    для UI-badge или branch-logic.

    S11 K3 W3: добавлен параметр ``strategy`` — outbound-сигнал для
    retriever'а о желаемой стратегии (``dense``/``hybrid``/``hyde``/
    ``multi_query``). Стратегия пишется в exchange property
    ``rag_strategy`` и в ``augment_result["strategy"]``, чтобы
    downstream-консьюмер мог веткой обработать результат разной
    природы (raw vectors vs lexical+semantic union).

    Usage::

        .rag_query(
            query_field="question",
            top_k=5,
            namespace="docs",
            strategy="hybrid",
            max_staleness_hours=72,
            output_property="augment_result",
        )

    Property ``augment_result`` = dict() форма для downstream-process'ов
    (см. :meth:`AugmentResult.to_dict`).
    """

    def __init__(
        self,
        query_field: str = "question",
        system_prompt: str = "",
        top_k: int = 5,
        namespace: str | None = None,
        strategy: str = "dense",
        max_staleness_hours: float | None = None,
        output_property: str = "augment_result",
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        if strategy not in _RAG_STRATEGIES:
            raise ValueError(
                f"unknown rag strategy '{strategy}'; expected one of {_RAG_STRATEGIES}"
            )
        self._query_field = query_field
        self._system_prompt = system_prompt
        self._top_k = top_k
        self._namespace = namespace
        self._strategy = strategy
        self._max_staleness = max_staleness_hours
        self._output_property = output_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        if isinstance(body, dict):
            query = body.get(self._query_field, "")
        else:
            query = str(body)
        if not query:
            exchange.set_property(self._output_property, None)
            return
        from src.backend.services.ai.rag_service import get_rag_service

        # S11 K4 W3: adaptive — селектор выбирает реальную стратегию
        # на основе query-features + feature_flag.
        effective_strategy = self._strategy
        if effective_strategy == "adaptive":
            from src.backend.core.config.features import feature_flags

            if feature_flags.adaptive_rag_strategy:
                from src.backend.services.ai.rag.strategy_selector import (
                    AdaptiveStrategySelector,
                )

                selector = AdaptiveStrategySelector()
                decision = await selector.select(query)
                effective_strategy = decision.strategy
                exchange.set_property("rag_strategy_overhead_ms", decision.elapsed_ms)
            else:
                effective_strategy = "dense"

        rag = get_rag_service()
        result = await rag.augment(
            query=query,
            system_prompt=self._system_prompt,
            top_k=self._top_k,
            namespace=self._namespace,
            max_staleness_hours=self._max_staleness,
        )
        payload = result.to_dict()
        # Прокидываем strategy в downstream:
        # — exchange property для branch-logic,
        # — поле augment_result для каждого консьюмера, читающего dict.
        payload["strategy"] = effective_strategy
        exchange.set_property("rag_strategy", effective_strategy)
        exchange.set_property(self._output_property, payload)

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {}
        if self._query_field != "question":
            spec["query_field"] = self._query_field
        if self._top_k != 5:
            spec["top_k"] = self._top_k
        if self._namespace is not None:
            spec["namespace"] = self._namespace
        if self._strategy != "dense":
            spec["strategy"] = self._strategy
        if self._max_staleness is not None:
            spec["max_staleness_hours"] = self._max_staleness
        if self._system_prompt:
            spec["system_prompt"] = self._system_prompt
        if self._output_property != "augment_result":
            spec["output_property"] = self._output_property
        return {"rag_query": spec}


class RagPIIRedactionProcessor(BaseProcessor):
    """PII-маскер для retrieved RAG chunks (Sprint 11 K1 W1).

    Применяется после :class:`RagQueryProcessor` к exchange property
    (``augment_result`` или указанному ``input_property``); маскирует
    ``citations[*].content``, ``documents[*].content`` и ``prompt``
    через :func:`services.ai.pii.retrieval_masker.mask_augment_result`.

    Активируется при ``feature_flags.rag_pii_retrieval_mask=True``
    (capability ``ai.rag.pii_redaction``). При OFF — passthrough без
    модификации payload.

    Usage::

        .rag_query(output_property="augment_result")
        .rag_pii_redact(input_property="augment_result")
        .llm_call(...)

    Безопасно для downstream consumers — input копируется (не мутируется).
    """

    def __init__(
        self,
        input_property: str = "augment_result",
        output_property: str | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        self._input_property = input_property
        self._output_property = output_property or input_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from src.backend.core.config.features import feature_flags

        if not feature_flags.rag_pii_retrieval_mask:
            return
        payload = exchange.properties.get(self._input_property)
        if not isinstance(payload, dict):
            return
        from src.backend.services.ai.pii.retrieval_masker import mask_augment_result

        masked = mask_augment_result(payload)
        exchange.set_property(self._output_property, masked)

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {}
        if self._input_property != "augment_result":
            spec["input_property"] = self._input_property
        if self._output_property != self._input_property:
            spec["output_property"] = self._output_property
        return {"rag_pii_redact": spec}


class RagIngestProcessor(BaseProcessor):
    """RAG ingest: добавление документа в vector store (S11 K3 W2).

    Принимает body как контент или явный ``source_property`` —
    отправляет в :meth:`RAGService.ingest`. Параметр ``modal``
    сохраняется в metadata как ``modal`` для downstream-консьюмеров
    мультимодального индекса (text/image/audio/video).

    Usage::

        .rag_ingest(
            source_property="document",
            modal="text",
            collection="docs",
        )

    Property ``ingest_doc_id`` хранит возвращённый id документа.
    """

    def __init__(
        self,
        source_property: str | None = None,
        modal: str = "text",
        collection: str = "default",
        output_property: str = "ingest_doc_id",
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        self._source_property = source_property
        self._modal = modal
        self._collection = collection
        self._output_property = output_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        if self._source_property:
            content = exchange.get_property(self._source_property)
        else:
            content = exchange.in_message.body
        if not content:
            exchange.set_property(self._output_property, None)
            return
        text = content if isinstance(content, str) else str(content)
        from src.backend.services.ai.rag_service import get_rag_service

        rag = get_rag_service()
        doc_id = await rag.ingest(
            content=text,
            metadata={"modal": self._modal, "collection": self._collection},
            namespace=self._collection,
        )
        exchange.set_property(self._output_property, doc_id)

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {"collection": self._collection}
        if self._source_property is not None:
            spec["source_property"] = self._source_property
        if self._modal != "text":
            spec["modal"] = self._modal
        if self._output_property != "ingest_doc_id":
            spec["output_property"] = self._output_property
        return {"rag_ingest": spec}


class SanitizePIIProcessor(BaseProcessor):
    """Маскирует PII в body перед передачей дальше."""

    def __init__(self, name: str | None = None) -> None:
        super().__init__(name)

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        if not isinstance(body, str):
            body = str(body)
        from src.backend.infrastructure.security.ai_sanitizer import get_ai_sanitizer

        sanitizer = get_ai_sanitizer()
        result = await sanitizer.sanitize(body)
        exchange.set_property("_pii_original", exchange.in_message.body)
        exchange.set_property("_pii_mapping", result.replacements)
        exchange.in_message.set_body(result.sanitized_text)

    def to_spec(self) -> dict[str, Any] | None:
        return {"sanitize_pii": {}}


class RestorePIIProcessor(BaseProcessor):
    """Восстанавливает замаскированные PII из exchange properties."""

    def __init__(self, name: str | None = None) -> None:
        super().__init__(name)

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        mapping = exchange.properties.get("_pii_mapping")
        if not mapping:
            return
        body = exchange.in_message.body
        if not isinstance(body, str):
            body = str(body)
        for placeholder, original in mapping.items():
            body = body.replace(placeholder, original)
        exchange.in_message.set_body(body)
        exchange.properties.pop("_pii_mapping", None)
        exchange.properties.pop("_pii_original", None)


class LLMFallbackProcessor(BaseProcessor):
    """Пробует несколько LLM-провайдеров по цепочке.

    При недоступности primary провайдера автоматически
    переключается на следующий. Полезно для production-надёжности.

    Usage::

        .call_llm_with_fallback(providers=["perplexity", "huggingface", "open_webui"])
    """

    def __init__(
        self,
        providers: list[str],
        *,
        model: str = "default",
        prompt_property: str = "_composed_prompt",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"llm_fallback({len(providers)})")
        self._providers = providers
        self._model = model
        self._prompt_property = prompt_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        prompt = exchange.properties.get(self._prompt_property)
        if prompt is None:
            prompt = (
                exchange.in_message.body
                if isinstance(exchange.in_message.body, str)
                else str(exchange.in_message.body)
            )

        from src.backend.services.ai.ai_agent import get_ai_agent_service

        agent = get_ai_agent_service()

        last_error: str | None = None
        for provider in self._providers:
            try:
                result = await agent.chat(
                    messages=[{"role": "user", "content": prompt}],
                    provider=provider,
                    model=self._model,
                )
                exchange.in_message.set_body(result)
                exchange.set_property("llm_provider_used", provider)
                return
            except Exception as exc:
                last_error = f"{provider}: {exc}"

        exchange.fail(f"All LLM providers failed. Last error: {last_error}")


class CacheProcessor(BaseProcessor):
    """Redis-кеш для результатов обработки.

    Проверяет кеш по ключу. При попадании — возвращает из кеша.
    При промахе — ставит property cached=False для downstream.

    Usage::

        .cache(key_fn=lambda ex: str(ex.in_message.body)[:100], ttl=3600)
    """

    def __init__(
        self,
        key_fn: Callable[[Exchange[Any]], str],
        *,
        ttl_seconds: int = 3600,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "cache_read")
        self._key_fn = key_fn
        self._ttl = ttl_seconds

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        key = f"dsl:cache:{self._key_fn(exchange)}"
        exchange.set_property("_cache_key", key)
        exchange.set_property("_cache_ttl", self._ttl)

        try:
            from src.backend.infrastructure.clients.storage.redis import redis_client

            cached = await redis_client.get(key)
            if cached is not None:
                exchange.set_out(
                    body=orjson.loads(cached), headers=dict(exchange.in_message.headers)
                )
                exchange.set_property("cached", True)
                return
        except (ConnectionError, TimeoutError, OSError):
            pass

        exchange.set_property("cached", False)


class CacheWriteProcessor(BaseProcessor):
    """Записывает результат в Redis-кеш после обработки.

    Записывает только если property cached=False (промах).
    Ставится после вычислительных процессоров.

    Usage::

        .cache_write(key_fn=lambda ex: str(ex.in_message.body)[:100], ttl=3600)
    """

    def __init__(
        self,
        key_fn: Callable[[Exchange[Any]], str],
        *,
        ttl_seconds: int = 3600,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "cache_write")
        self._key_fn = key_fn
        self._ttl = ttl_seconds

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        if exchange.properties.get("cached", True):
            return

        key = exchange.properties.get(
            "_cache_key", f"dsl:cache:{self._key_fn(exchange)}"
        )
        body = (
            exchange.out_message.body
            if exchange.out_message
            else exchange.in_message.body
        )

        try:
            from src.backend.infrastructure.clients.storage.redis import redis_client

            data = orjson.dumps(body, default=str).decode()
            await redis_client.set_if_not_exists(key=key, value=data, ttl=self._ttl)
        except (ConnectionError, TimeoutError, OSError):
            pass


class GuardrailsProcessor(BaseProcessor):
    """Проверяет LLM output на безопасность и соответствие ожиданиям.

    Валидации: max_length, blocklist regex, required dict keys,
    + опциональные внешние провайдеры Lakera Guard / Rebuff (Sprint 11 K1 W2)
    с per-tenant конфигурацией через TenantContext.

    Активация внешних провайдеров: ``feature_flags.guardrails_per_tenant=True``;
    конфиг берётся из ``providers_config`` или TenantContext-resolver'а.
    """

    def __init__(
        self,
        *,
        max_length: int = 10000,
        blocked_patterns: list[str] | None = None,
        required_fields: list[str] | None = None,
        providers_config: Any = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "guardrails")
        self._max_length = max_length
        self._blocked = blocked_patterns or []
        self._required = required_fields or []
        self._providers_config = providers_config

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        import re

        body = exchange.in_message.body
        text = body if isinstance(body, str) else str(body)

        if len(text) > self._max_length:
            exchange.fail(
                f"Guardrail: output too long ({len(text)} > {self._max_length})"
            )
            return

        for pattern in self._blocked:
            if re.search(pattern, text, re.IGNORECASE):
                exchange.fail(f"Guardrail: blocked pattern detected: {pattern}")
                return

        if self._required and isinstance(body, dict):
            missing = [f for f in self._required if f not in body]
            if missing:
                exchange.fail(f"Guardrail: missing required fields: {missing}")
                return

        await self._check_external_providers(exchange, text)

    async def _check_external_providers(
        self, exchange: Exchange[Any], text: str
    ) -> None:
        """Запустить Lakera/Rebuff если активны (Sprint 11 K1 W2)."""
        from src.backend.core.config.features import feature_flags

        if not feature_flags.guardrails_per_tenant:
            return
        config = self._resolve_config()
        if not config or not config.enabled_providers:
            return

        if "lakera" in config.enabled_providers:
            try:
                from src.backend.services.ai.guardrails.lakera_client import (
                    LakeraClient,
                )

                lakera_result = await LakeraClient().screen(text)
                if (
                    lakera_result.flagged
                    and lakera_result.score >= config.thresholds.lakera_threshold
                ):
                    exchange.fail(
                        f"Guardrail/lakera: flagged (score={lakera_result.score:.2f})"
                    )
                    return
            except Exception as exc:  # noqa: BLE001
                if config.block_on_failure:
                    exchange.fail(f"Guardrail/lakera: provider error: {exc}")
                    return

        if "rebuff" in config.enabled_providers:
            try:
                from src.backend.services.ai.guardrails.rebuff_client import (
                    RebuffClient,
                )

                rebuff_result = await RebuffClient().detect(text)
                if (
                    rebuff_result.injected
                    and rebuff_result.score >= config.thresholds.rebuff_threshold
                ):
                    exchange.fail(
                        f"Guardrail/rebuff: prompt injection (score={rebuff_result.score:.2f})"
                    )
                    return
            except Exception as exc:  # noqa: BLE001
                if config.block_on_failure:
                    exchange.fail(f"Guardrail/rebuff: provider error: {exc}")
                    return

        if "nemo" in config.enabled_providers:
            try:
                from src.backend.services.ai.guardrails.nemo_client import (
                    get_nemo_guardrails_runtime,
                )

                runtime = get_nemo_guardrails_runtime()
                if runtime is None:
                    return  # GPU/FF unavailable — skip NeMo silently
                prompt = exchange.get_property("llm.original_prompt", "")
                nemo_result = await runtime.check_output(prompt=prompt, completion=text)
                if not nemo_result.get("safe", True):
                    exchange.fail(
                        f"Guardrail/nemo: {nemo_result.get('reason', 'unsafe output')}"
                    )
                    return
            except Exception as exc:  # noqa: BLE001
                if config.block_on_failure:
                    exchange.fail(f"Guardrail/nemo: provider error: {exc}")
                    return

    def _resolve_config(self) -> Any:
        """Возвращает per-tenant guardrails config или None.

        Источники в порядке приоритета:
        1. Explicit ``providers_config`` переданный в конструктор.
        2. Resolver на основе TenantContext (если задан в DI).
        3. ``None`` — guardrails-провайдеры выключены.
        """
        if self._providers_config is not None:
            return self._providers_config
        try:
            from src.backend.core.tenancy import current_tenant
            from src.backend.services.ai.guardrails.tenant_config import (
                get_default_config,
            )
        except ImportError:
            return None
        tenant = current_tenant()
        if tenant is None:
            return None
        return get_default_config()


class SemanticRouterProcessor(BaseProcessor):
    """Маршрутизация по семантическому сходству — RAG-based intent routing.

    Принимает text input, ищет ближайший intent через RAG vector search,
    делегирует выполнение в соответствующий route_id.

    Usage::

        .semantic_route(intents={
            "order_status": "route.orders",
            "complaint": "route.support",
            "billing": "route.billing",
        }, default_route="route.general")
    """

    def __init__(
        self,
        intents: dict[str, str],
        *,
        default_route: str | None = None,
        query_field: str = "question",
        threshold: float = 0.5,
        namespace: str = "intents",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "semantic_router")
        self._intents = intents
        self._default_route = default_route
        self._query_field = query_field
        self._threshold = threshold
        self._namespace = namespace

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        if isinstance(body, dict):
            query = body.get(self._query_field, "")
        else:
            query = str(body)

        if not query:
            if self._default_route:
                await self._route_to(self._default_route, exchange, context)
                return
            exchange.fail("SemanticRouter: empty query and no default_route")
            return

        try:
            from src.backend.services.ai.rag_service import get_rag_service

            rag = get_rag_service()
            results = await rag.search(query=query, top_k=1, namespace=self._namespace)
        except (ImportError, ConnectionError, TimeoutError, RuntimeError) as exc:
            if self._default_route:
                exchange.set_property("semantic_route_fallback", str(exc))
                await self._route_to(self._default_route, exchange, context)
                return
            exchange.fail(f"SemanticRouter RAG search failed: {exc}")
            return

        target_intent: str | None = None
        score = 0.0
        if results:
            top = results[0]
            score = top.get("score", 0.0) if isinstance(top, dict) else 0.0
            intent_name = (
                top.get("intent") or top.get("metadata", {}).get("intent")
                if isinstance(top, dict)
                else None
            )
            if intent_name and score >= self._threshold:
                target_intent = intent_name

        target_route = self._intents.get(target_intent or "", self._default_route)
        if not target_route:
            exchange.fail(
                f"SemanticRouter: no matching intent for query (score={score:.3f})"
            )
            return

        exchange.set_property("semantic_route_intent", target_intent)
        exchange.set_property("semantic_route_score", score)
        await self._route_to(target_route, exchange, context)

    @staticmethod
    async def _route_to(
        route_id: str, exchange: Exchange[Any], context: ExecutionContext
    ) -> None:
        from src.backend.dsl.engine.processors.base import SubPipelineExecutor

        result, error = await SubPipelineExecutor.execute_route(
            route_id,
            exchange.in_message.body,
            dict(exchange.in_message.headers),
            context,
        )
        if error:
            exchange.fail(f"Semantic route {route_id} failed: {error}")
            return
        exchange.set_out(body=result, headers=dict(exchange.in_message.headers))


class GetFeedbackExamplesProcessor(BaseProcessor):
    """Достаёт примеры из AI Feedback RAG для few-shot prompting.

    Ищет похожие размеченные ответы агентов в RAG-индексе с
    фильтрацией по метке оператора: отдельно ``positive`` (как
    пример хороших ответов) и ``negative`` (примеры ответов,
    которых следует избегать). Результат складывается в
    ``exchange.properties[inject_as]`` в формате::

        {
          "positive": [{"query": "...", "response": "..."}, ...],
          "negative": [{"query": "...", "response": "..."}, ...],
        }

    Используется как шаг перед ``LLMCallProcessor`` / шаблонизацией
    промпта агента.

    Пример DSL YAML::

        - kind: get_feedback_examples
          config:
            query_from: body.query
            agent_id: risk_assessor
            positive_k: 3
            negative_k: 2
            min_similarity: 0.75
            inject_as: feedback_examples
    """

    _NAMESPACE = "ai_feedback"

    def __init__(
        self,
        *,
        query_from: str = "body.query",
        agent_id: str | None = None,
        positive_k: int = 3,
        negative_k: int = 2,
        min_similarity: float = 0.0,
        inject_as: str = "feedback_examples",
        name: str | None = None,
    ) -> None:
        """Инициализирует процессор.

        Args:
            query_from: Путь к тексту запроса в exchange
                (``body.<field>`` или ``property:<name>``).
            agent_id: Фильтрация примеров по агенту (только если
                ``metadata.agent_id`` совпадает).
            positive_k: Сколько положительных примеров брать.
            negative_k: Сколько отрицательных примеров брать.
            min_similarity: Минимальный порог сходства (0..1).
            inject_as: Ключ в ``exchange.properties`` для результата.
            name: Имя процессора для трейсов/метрик.
        """
        super().__init__(name or "get_feedback_examples")
        self._query_from = query_from
        self._agent_id = agent_id
        self._positive_k = max(0, positive_k)
        self._negative_k = max(0, negative_k)
        self._min_similarity = min_similarity
        self._inject_as = inject_as

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Выполняет поиск feedback-примеров и помещает их в properties."""
        query = self._extract_query(exchange)
        if not query:
            exchange.set_property(self._inject_as, {"positive": [], "negative": []})
            return

        positive = await self._search(query, "positive", self._positive_k)
        negative = await self._search(query, "negative", self._negative_k)
        exchange.set_property(
            self._inject_as, {"positive": positive, "negative": negative}
        )

    def _extract_query(self, exchange: Exchange[Any]) -> str:
        """Извлекает query-текст из exchange по пути ``query_from``.

        Args:
            exchange: Текущий exchange.

        Returns:
            Строковое представление запроса.
        """
        path = self._query_from
        body = exchange.in_message.body
        if path.startswith("property:"):
            return str(exchange.properties.get(path.split(":", 1)[1], "") or "")
        if path.startswith("body."):
            field = path.split(".", 1)[1]
            if isinstance(body, dict):
                return str(body.get(field, "") or "")
            return str(body or "")
        if path == "body":
            return str(body or "")
        if isinstance(body, dict) and path in body:
            return str(body[path] or "")
        return str(body or "")

    async def _search(self, query: str, label: str, top_k: int) -> list[dict[str, str]]:
        """Ищет примеры по метке и формирует пары ``{query, response}``.

        Args:
            query: Запрос пользователя.
            label: ``positive`` / ``negative``.
            top_k: Сколько примеров запрашивать.

        Returns:
            Список пар (может быть пустым при отсутствии RAG-данных).
        """
        if top_k <= 0:
            return []
        try:
            from src.backend.services.ai.rag_service import get_rag_service

            rag = get_rag_service()
            results = await rag.search(
                query=query, top_k=top_k * 2, namespace=self._NAMESPACE
            )
        except Exception as _:
            return []

        examples: list[dict[str, str]] = []
        for row in results or []:
            metadata = row.get("metadata") or {}
            if metadata.get("source") != "ai_feedback":
                continue
            if metadata.get("label") != label:
                continue
            if self._agent_id and metadata.get("agent_id") != self._agent_id:
                continue
            score = float(row.get("score") or row.get("similarity") or 0.0)
            if score < self._min_similarity:
                continue
            examples.append(self._parse_example(row.get("document", "")))
            if len(examples) >= top_k:
                break
        return examples

    @staticmethod
    def _parse_example(content: str) -> dict[str, str]:
        """Парсит чанк вида ``Q: ...\\nA: ...`` в словарь.

        Args:
            content: Текст чанка из RAG-store.

        Returns:
            ``{"query": str, "response": str}``.
        """
        q_part = ""
        a_part = ""
        if content.startswith("Q:"):
            parts = content.split("\nA:", 1)
            q_part = parts[0][2:].strip()
            if len(parts) == 2:
                a_part = parts[1].strip()
        else:
            a_part = content.strip()
        return {"query": q_part, "response": a_part}
