from __future__ import annotations
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors import (
    DispatchActionProcessor,
    PipelineRefProcessor,
)
from src.backend.dsl.engine.processors.invoke import InvokeProcessor

class AiOpsMixin:
    """AI (llm_structured + ml_predict) для IntegrationCoreMixin. S62 W3 extraction."""

    __slots__ = ()

    def llm_structured(
        self,
        *,
        model: str,
        output_schema: Any,
        prompt: str,
        retry: int = 3,
        temperature: float = 0.0,
        cost_budget_usd: float | None = None,
        to: str = "body.llm_result",
        name: str | None = None,
    ) -> RouteBuilder:
        """LLM-вызов с гарантированным Pydantic-объектом.

        Wave: ``[wave:s8/k4-llm-structured-finale]``. Обёртка над
        :class:`LLMStructuredProcessor` (instructor + litellm). Поддержка
        outer retry на network errors (через ``make_async_retry``) и
        inner — instructor ``max_retries`` для Pydantic-валидации.

        Args:
            model: Идентификатор в формате ``<provider>/<model>``
                (``anthropic/claude-sonnet-4-6``, ``openai/gpt-4o``).
            output_schema: ``type[BaseModel]`` или ``"module:Class"`` /
                имя класса в ``ServiceSchemaRegistry``.
            prompt: Шаблон промпта; ``${body.x}`` / ``${properties.y}``
                подставляются из exchange.
            retry: instructor inner ``max_retries`` (Pydantic-валидация).
            temperature: Sampling-temperature; для structured output
                0.0 (детерминизм) по умолчанию.
            cost_budget_usd: Опц. бюджет; превышение → ``exchange.fail``.
            to: Путь записи результата (``body.<field>`` / ``body`` /
                ``property:<name>``).
            name: Имя процессора в трейсах/метриках.
        """
        from src.backend.dsl.engine.processors.llm_structured import (
            LLMStructuredProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            LLMStructuredProcessor(
                model=model,
                output_schema=output_schema,
                prompt=prompt,
                retry=retry,
                temperature=temperature,
                cost_budget_usd=cost_budget_usd,
                to=to,
                name=name,
            )
        )

    def ml_predict(
        self,
        model: str,
        *,
        input_field: str = "body.features",
        output_property: str = "ml_prediction",
        model_type: str | None = None,
        name: str | None = None,
    ) -> RouteBuilder:
        """Выполняет ML-инференс через локальный filesystem model registry.

        Wave: ``[wave:s29/local-models-repository]``. Использует
        :class:`MLPredictProcessor` + :class:`MLModelLoader`.

        Модель ищется в ``${AI_WORKSPACE}/models/<model>/`` через
        :class:`LocalFSModelRegistry`. Поддерживает torch, onnx, sklearn,
        catboost, lightgbm.

        Args:
            model: Имя модели в LocalFSModelRegistry.
            input_field: dotted-path к входным данным (default ``body.features``).
            output_property: Куда положить результат инференса.
            model_type: Явный тип модели (default — по расширению файла).
            name: Имя процессора в трейсах.
        """
        from src.backend.dsl.engine.processors.ml_predict import MLPredictProcessor

        return self._add(  # type: ignore[attr-defined]
            MLPredictProcessor(
                model_endpoint=model,
                input_field=input_field,
                output_property=output_property,
                model_type=model_type,
                name=name,
            )
        )

