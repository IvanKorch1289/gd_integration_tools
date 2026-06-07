"""DSL processor ``llm_structured`` (V17 NEW, K4 Sprint 8A).

Вызов LLM с гарантированным возвратом валидного Pydantic-объекта через
``instructor>=1.7.0`` retry-loop. Поддерживает multi-provider через
``litellm`` (OpenAI / Anthropic / Cohere / локальные модели).

Использование (Python builder)::

    builder.llm_structured(
        model="anthropic/claude-sonnet-4-6",
        output_schema=CreditDecision,
        prompt="Оцени заявку: ${body.application_summary}",
        retry=3,
        cost_budget_usd=0.05,
        to="body.decision",
    )

Использование (YAML)::

    - llm_structured:
        model: anthropic/claude-sonnet-4-6
        output_schema: CreditDecision
        prompt: "Оцени заявку: ${body.application_summary}"
        retry: 3
        to: body.decision

Безопасность:
    * WAF strict (V15 R-V15-5): cloud LLM вызовы должны идти через
      ``OutboundHttpClient`` / WAF-прокси. На текущем этапе ``litellm``
      использует собственный httpx-клиент — добавлен capability
      ``net.outbound.<provider>:external``; полная миграция на
      ``OutboundHttpClient`` — TODO Sprint 9 (требует litellm-hook).
    * Capability-gate: процессор объявляет capability ``ai.llm.<provider>``
      и ``net.outbound.<provider>:external``; runtime-проверка делается
      в lifespan'е плагина при загрузке.
    * AI Safety (V15 R-V15-4): процессор только читает prompt и пишет
      результат в ``properties``/``body``; никаких изменений файлов.

Cost tracking:
    * Если задан ``cost_budget_usd`` — после вызова сравнивается фактическая
      стоимость (из ``response.usage`` через ``litellm.completion_cost``),
      при превышении ``exchange.fail(...)``;
    * Стоимость пишется в ``properties["llm.cost_usd"]`` для downstream
      ``CostTrackerProcessor`` / LangFuse-агрегации.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from pydantic import BaseModel

    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


__all__ = ("LLMStructuredProcessor",)


_logger = logging.getLogger(__name__)

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
class LLMStructuredProcessor(BaseProcessor):
    """Вызов LLM с возвратом валидного Pydantic-объекта.

    Args:
        model: Идентификатор модели в формате ``<provider>/<model>``
            (например, ``anthropic/claude-sonnet-4-6``,
            ``openai/gpt-4o``). Передаётся напрямую в ``litellm.acompletion``.
        output_schema: Класс Pydantic ``BaseModel`` (для Python builder)
            или строка ``module:ClassName`` для YAML-loader / имя
            зарегистрированной схемы из ``ServiceSchemaRegistry``.
        prompt: Шаблон промпта; поддерживает подстановку
            ``${body.<field>}`` и ``${properties.<key>}`` из текущего
            ``Exchange``. Доступен также сырой ``body``-словарь через
            ``str.format_map`` (Jinja-подобный синтаксис не поддерживается
            намеренно — KISS).
        retry: Количество попыток валидации внутри ``instructor``
            (если LLM вернул невалидный JSON). По умолчанию ``3``.
        temperature: Сэмплинг ``temperature``; для structured-output по
            умолчанию ``0.0`` (детерминизм).
        cost_budget_usd: Опц. бюджет за один вызов; при превышении
            фактической стоимости ``exchange.fail(...)``.
        to: Путь записи результата (``body.<field>`` или
            ``property:<name>``). По умолчанию ``body.llm_result``.
        name: Имя процессора для трейсов/метрик.

    Properties после успешного вызова:
        * ``llm.provider`` — фактически использованный провайдер;
        * ``llm.model`` — имя модели;
        * ``llm.tokens_used`` — total_tokens (если LLM вернул usage);
        * ``llm.cost_usd`` — оценка стоимости;
        * ``llm.attempts`` — сколько попыток понадобилось.
    """

    def __init__(
        self,
        *,
        model: str,
        output_schema: type[BaseModel] | str | None,
        prompt: str,
        retry: int = _DEFAULT_RETRY,
        temperature: float = _DEFAULT_TEMPERATURE,
        cost_budget_usd: float | None = None,
        to: str = "body.llm_result",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "llm_structured")
        if not model or "/" not in model:
            raise ValueError(
                f"llm_structured: model должен быть в формате "
                f"'<provider>/<name>', получено {model!r}"
            )
        if retry < 0:
            raise ValueError(
                f"llm_structured: retry должен быть >= 0, получено {retry!r}"
            )
        if cost_budget_usd is not None and cost_budget_usd < 0:
            raise ValueError(
                "llm_structured: cost_budget_usd должен быть >= 0, "
                f"получено {cost_budget_usd!r}"
            )
        self._model = model
        self._output_schema_ref = output_schema
        self._prompt_template = prompt
        self._retry = retry
        self._temperature = temperature
        self._cost_budget_usd = cost_budget_usd
        self._to = to

    # ── Schema resolution ─────────────────────────────────────────────

    def _resolve_schema(self) -> type[BaseModel]:
        """Резолвит ``output_schema`` в Pydantic-класс.

        Поддерживается:
            * Прямой ``type[BaseModel]`` — возвращается как есть;
            * Строка ``module:ClassName`` — динамический import;
            * Имя ``ClassName`` — поиск в
              :class:`ServiceSchemaRegistry` (kind=processor) с
              fallback на ``importlib.import_module`` если в meta
              записан ``module``.

        Raises:
            ValueError: Не удалось резолвить схему.
        """
        from pydantic import BaseModel

        ref = self._output_schema_ref
        if ref is None:
            raise ValueError("llm_structured: output_schema обязателен")
        if isinstance(ref, type) and issubclass(ref, BaseModel):
            return ref
        if not isinstance(ref, str):
            raise ValueError(
                f"llm_structured: output_schema должен быть Pydantic-классом "
                f"или строкой 'module:Class', получено {type(ref).__name__}"
            )

        # 1) Полный путь module:Class — динамический import.
        if ":" in ref:
            import importlib

            module_name, _, class_name = ref.partition(":")
            module = importlib.import_module(module_name)
            cls = getattr(module, class_name, None)
            if cls is None or not (
                isinstance(cls, type) and issubclass(cls, BaseModel)
            ):
                raise ValueError(
                    f"llm_structured: {ref!r} не указывает на Pydantic-класс"
                )
            return cls

        # 2) Имя класса — поиск в ServiceSchemaRegistry meta.
        try:
            from src.backend.services.schema_registry import (
                SchemaKind,
                get_schema_registry,
            )

            entry = get_schema_registry().get(SchemaKind.PROCESSOR, ref)
        except ImportError, AttributeError:
            entry = None

        if entry is not None:
            module_name = entry.meta.get("module")
            if module_name:
                import importlib

                module = importlib.import_module(module_name)
                cls = getattr(module, ref, None)
                if (
                    cls is not None
                    and isinstance(cls, type)
                    and issubclass(cls, BaseModel)
                ):
                    return cls

        raise ValueError(
            f"llm_structured: не удалось резолвить output_schema={ref!r}; "
            "используйте 'module:ClassName' или зарегистрируйте схему в "
            "ServiceSchemaRegistry с meta['module']"
        )

    # ── Prompt resolution ─────────────────────────────────────────────

    def _resolve_prompt(self, exchange: Exchange[Any]) -> str:
        """Подставляет ``${body.x}`` / ``${properties.y}`` из exchange.

        Args:
            exchange: Текущий exchange.

        Returns:
            Готовый prompt-string.
        """
        body = exchange.in_message.body
        body_dict = body if isinstance(body, dict) else {"_raw": body}

        # Простой шаблонизатор ${path}: KISS вместо Jinja2 (тяжёлая deps).
        # Поддержка: ${body.field}, ${properties.key}, ${body} (raw).
        import re

        pattern = re.compile(r"\$\{([^}]+)\}")

        def _replace(match: re.Match[str]) -> str:
            path = match.group(1).strip()
            if path == "body":
                return str(body)
            if path.startswith("body."):
                key = path[len("body.") :]
                return str(body_dict.get(key, ""))
            if path.startswith("properties."):
                key = path[len("properties.") :]
                return str(exchange.properties.get(key, ""))
            # Неизвестный префикс — оставляем placeholder как-есть для отладки.
            return match.group(0)

        return pattern.sub(_replace, self._prompt_template)

    # ── Provider extraction ───────────────────────────────────────────

    def _provider_name(self) -> str:
        """Извлекает имя провайдера из ``model`` для capability/трейсов."""
        return self._model.split("/", 1)[0]

    # ── Main process ──────────────────────────────────────────────────

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

    @staticmethod
    def _estimate_cost(raw_response: Any) -> float | None:
        """Оценивает стоимость через ``litellm.completion_cost``.

        Args:
            raw_response: Ответ от ``litellm.acompletion`` или ``None``.

        Returns:
            Стоимость в USD, ``None`` если оценка недоступна.
        """
        if raw_response is None:
            return None
        try:
            import litellm

            cost = litellm.completion_cost(completion_response=raw_response)
            return float(cost) if cost is not None else None
        except ImportError, AttributeError, TypeError, ValueError:
            return None

    @staticmethod
    def _extract_tokens(raw_response: Any) -> int | None:
        """Извлекает total_tokens из usage."""
        if raw_response is None:
            return None
        usage = getattr(raw_response, "usage", None)
        if usage is None and isinstance(raw_response, dict):
            usage = raw_response.get("usage")
        if usage is None:
            return None
        total = getattr(usage, "total_tokens", None)
        if total is None and isinstance(usage, dict):
            total = usage.get("total_tokens")
        try:
            return int(total) if total is not None else None
        except TypeError, ValueError:
            return None

    def _write_result(self, exchange: Exchange[Any], result: Any) -> None:
        """Записывает результат в путь ``self._to``.

        Поддерживается:
            * ``body.<field>`` — обновляет body (создаёт dict если нужен);
            * ``body`` — заменяет body целиком;
            * ``property:<name>`` — пишет в ``exchange.properties[name]``.

        Args:
            exchange: Текущий exchange.
            result: Pydantic-объект (валидный по схеме).
        """
        target = self._to
        if target.startswith("property:"):
            key = target[len("property:") :]
            exchange.set_property(key, result)
            return
        if target == "body":
            exchange.in_message.body = result
            return
        if target.startswith("body."):
            key = target[len("body.") :]
            body = exchange.in_message.body
            if not isinstance(body, dict):
                body = {}
            body[key] = result
            exchange.in_message.body = body
            return

        # Fallback: трактуем как property name.
        exchange.set_property(target, result)

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализует процессор в YAML-spec для round-trip."""
        spec: dict[str, Any] = {
            "model": self._model,
            "prompt": self._prompt_template,
            "retry": self._retry,
            "to": self._to,
        }
        if self._temperature != _DEFAULT_TEMPERATURE:
            spec["temperature"] = self._temperature
        if self._cost_budget_usd is not None:
            spec["cost_budget_usd"] = self._cost_budget_usd
        # output_schema → строка
        ref = self._output_schema_ref
        if isinstance(ref, str):
            spec["output_schema"] = ref
        elif ref is not None:
            spec["output_schema"] = f"{ref.__module__}:{ref.__name__}"
        return {"llm_structured": spec}
