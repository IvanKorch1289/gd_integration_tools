from __future__ import annotations
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger
from src.backend.dsl.registry import processor

if TYPE_CHECKING:

    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

_logger = get_logger(__name__)

# Дефолтный ``temperature`` для structured-output: детерминизм важнее
# креативности при заполнении схемы.
_DEFAULT_TEMPERATURE: float = 0.0
# Максимальное число instructor-retries (внутренний цикл валидации Pydantic).
_DEFAULT_RETRY: int = 3

@processor(
    "llm_structured",
    namespace="core",
    spec_schema={
        "type": "object",
        "required": ["model", "output_schema", "prompt"],
        "properties": {
            "model": {"type": "string"},
            "output_schema": {"type": ["string", "object", "null"]},
            "prompt": {"type": "string"},
            "retry": {"type": "integer", "minimum": 0, "default": _DEFAULT_RETRY},
            "temperature": {
                "type": "number",
                "minimum": 0.0,
                "default": _DEFAULT_TEMPERATURE,
            },
            "cost_budget_usd": {"type": ["number", "null"]},
            "to": {"type": "string"},
        },
    },
    capabilities=("ai.llm.litellm", "net.outbound.litellm:external"),
    meta={"tier": 2, "category": "ai", "version": "v17"},
    tags=("ai", "llm", "structured-output"),
)

class ProcessMixin:
    """process + call_with_completion (LLM call flow) для LLMStructuredProcessor. S65 W2 extraction."""

    __slots__ = ()

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Выполняет LLM-вызов и записывает результат в exchange.

        Алгоритм:
            1. Резолвим Pydantic-схему и prompt;
            2. Вызываем ``instructor.from_litellm(litellm.acompletion)``
               с ``response_model=schema`` и ``max_retries=retry``;
            3. Outer ``tenacity``-retry — на network-ошибки
               (``ConnectionError`` / ``TimeoutError``);
            4. Считаем стоимость через ``litellm.completion_cost`` и
               сравниваем с ``cost_budget_usd``;
            5. Записываем результат в ``to`` (body.path или property:name).

        При ошибке (validation / network / budget) → ``exchange.fail(...)``.
        """
        try:
            schema = self._resolve_schema()
        except (ValueError, ImportError) as exc:
            exchange.fail(f"llm_structured schema error: {exc}")
            return

        prompt = self._resolve_prompt(exchange)

        # Lazy-import тяжёлых зависимостей: instructor / litellm / tenacity.
        try:
            import instructor  # type: ignore[import-not-found]
            import litellm  # type: ignore[import-not-found]
        except ImportError as exc:
            exchange.fail(
                "llm_structured: instructor/litellm не установлены; "
                f"добавьте extras 'ai-2026' (uv sync --extra ai-2026): {exc}"
            )
            return

        from src.backend.infrastructure.resilience.retry import make_async_retry

        provider = self._provider_name()
        client = instructor.from_litellm(litellm.acompletion)

        # Outer-retry: только сетевые ошибки. Pydantic-валидация — внутри
        # instructor через max_retries; её исключения не повторяем здесь,
        # чтобы не множить дорогие LLM-вызовы.
        @make_async_retry(
            max_attempts=2,
            initial_backoff=1.0,
            multiplier=2.0,
            on=(ConnectionError, TimeoutError),
        )
        async def _call() -> Any:
            """Один вызов LLM через instructor."""
            return await client.create(
                model=self._model,
                response_model=schema,
                messages=[{"role": "user", "content": prompt}],
                max_retries=self._retry,
                temperature=self._temperature,
            )

        try:
            result, raw_response = await self._call_with_completion(_call)
        except Exception as exc:
            _logger.warning(
                "llm_structured failed: model=%s provider=%s error=%s",
                self._model,
                provider,
                exc,
            )
            exchange.fail(f"llm_structured failed: {exc}")
            return

        # ── Cost tracking ──
        cost_usd = self._estimate_cost(raw_response)
        if cost_usd is not None:
            exchange.set_property("llm.cost_usd", cost_usd)
            if self._cost_budget_usd is not None and cost_usd > self._cost_budget_usd:
                exchange.fail(
                    f"llm_structured cost budget exceeded: "
                    f"{cost_usd:.6f} > {self._cost_budget_usd:.6f} USD"
                )
                return

        # Tokens (если есть в usage).
        tokens = self._extract_tokens(raw_response)
        if tokens:
            exchange.set_property("llm.tokens_used", tokens)

        exchange.set_property("llm.provider", provider)
        exchange.set_property("llm.model", self._model)

        # ── Write result ──
        self._write_result(exchange, result)

    async def _call_with_completion(self, call: Any) -> tuple[Any, Any]:
        """Вызывает instructor и возвращает ``(parsed_obj, raw_response)``.

        ``instructor>=1.7`` поддерживает ``create_with_completion`` для
        получения raw response (для cost-extraction). Если метод
        недоступен — fallback к обычному ``call()``; тогда ``raw_response``
        будет ``None`` и cost-tracking не работает.

        Args:
            call: Coroutine, выполняющий instructor-вызов.

        Returns:
            Tuple ``(parsed_obj, raw_response_or_None)``.
        """
        # Прямой call() → результат валидации (Pydantic-объект). Raw
        # response недоступен: instructor.from_litellm обёртывает acompletion
        # и не пробрасывает usage наружу. Cost-tracking работает только
        # через litellm.completion_cost(); raw_response = None.
        result = await call()
        return result, None

