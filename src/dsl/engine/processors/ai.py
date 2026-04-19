"""AI/ML DSL процессоры — LLM, RAG, PII, prompt composition."""

from typing import Any, Callable

import orjson

from app.dsl.engine.context import ExecutionContext
from app.dsl.engine.exchange import Exchange
from app.dsl.engine.processors.base import BaseProcessor

__all__ = (
    "PromptComposerProcessor", "LLMCallProcessor", "LLMParserProcessor",
    "TokenBudgetProcessor", "VectorSearchProcessor",
    "SanitizePIIProcessor", "RestorePIIProcessor",
)


class PromptComposerProcessor(BaseProcessor):
    """Строит промпт из шаблона + контекст из exchange properties."""

    def __init__(self, template: str, context_property: str = "vector_results", output_property: str = "_composed_prompt", name: str | None = None) -> None:
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


class LLMCallProcessor(BaseProcessor):
    """Вызывает LLM через AI Agent с PII-маскировкой."""

    def __init__(self, provider: str | None = None, model: str | None = None, prompt_property: str = "_composed_prompt", name: str | None = None) -> None:
        super().__init__(name)
        self._provider = provider
        self._model = model
        self._prompt_property = prompt_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        prompt = exchange.properties.get(self._prompt_property)
        if prompt is None:
            prompt = exchange.in_message.body if isinstance(exchange.in_message.body, str) else str(exchange.in_message.body)
        try:
            from app.services.ai_agent import get_ai_agent_service
            agent = get_ai_agent_service()
            result = await agent.chat(message=prompt, provider=self._provider, model=self._model)
            exchange.in_message.set_body(result)
        except ImportError as exc:
            exchange.fail(f"AI agent service unavailable: {exc}")
        except (ConnectionError, TimeoutError, RuntimeError) as exc:
            exchange.fail(f"LLM call failed: {exc}")


class LLMParserProcessor(BaseProcessor):
    """Парсит ответ LLM в структурированный формат."""

    def __init__(self, schema: type | None = None, format: str = "json", name: str | None = None) -> None:
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

    def __init__(self, max_tokens: int = 4096, source_property: str | None = None, name: str | None = None) -> None:
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
                text = encoder.decode(tokens[:self._max_tokens]) + "\n...[truncated]"
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

    def __init__(self, query_field: str = "question", top_k: int = 5, namespace: str | None = None, output_property: str = "vector_results", name: str | None = None) -> None:
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
        from app.services.rag_service import get_rag_service
        rag = get_rag_service()
        results = await rag.search(query=query, top_k=self._top_k, namespace=self._namespace)
        exchange.set_property(self._output_property, results)


class SanitizePIIProcessor(BaseProcessor):
    """Маскирует PII в body перед передачей дальше."""

    def __init__(self, name: str | None = None) -> None:
        super().__init__(name)

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        if not isinstance(body, str):
            body = str(body)
        from app.core.security.ai_sanitizer import get_ai_sanitizer
        sanitizer = get_ai_sanitizer()
        result = await sanitizer.sanitize(body)
        exchange.set_property("_pii_original", exchange.in_message.body)
        exchange.set_property("_pii_mapping", result.replacements)
        exchange.in_message.set_body(result.sanitized_text)


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
