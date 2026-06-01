"""MLPredictProcessor — DSL step для локального ML-инференса.

Wave: ``[wave:s29/local-models-repository]``.

Использует :class:`MLModelLoader` для lazy-loading модели и выполняет
инференс. Результат кладётся в ``exchange.set_property(output_property, ...)``.

Usage (YAML)::

    steps:
      - ml_predict: {model: credit_scoring, input_field: body.features, output_property: score}

Usage (Python builder)::

    RouteBuilder.from_(...).ml_predict("credit_scoring", input_field="body.features").build()

Capabilities required: ``ml.predict``.
"""

from __future__ import annotations

import logging
from typing import Any

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

__all__ = ("MLPredictProcessor",)

_logger = logging.getLogger("dsl.processors.ml_predict")


class MLPredictProcessor(BaseProcessor):
    """Процессор ML-инференса из локального filesystem model registry.

    Загружает модель по имени из локального реестра
    (``${AI_WORKSPACE}/models/<name>/``), выполняет инференс на входных
    данных из ``exchange.in_message.body[input_field]``, результат пишет в
    ``exchange.properties[output_property]``.

    Поддерживаетые форматы: torch, torchscript, onnx, sklearn, catboost, lightgbm.

    Атрибуты:
        model_endpoint: Имя модели в LocalFSModelRegistry (не путь к файлу).
        input_field: dotted-path к входным данным в body
            (default ``body.features``).
        output_property: Имя property для результата
            (default ``ml_prediction``).
        model_type: Явный тип модели (по умолчанию определяется по расширению).
        fallback_on_error: Если ``True`` (default) — при ошибке инференса
            устанавливает ``output_property`` в ``None`` вместо ``exchange.fail``.
    """

    side_effect = SideEffectKind.SIDE_EFFECTING
    compensatable = False

    def __init__(
        self,
        *,
        model_endpoint: str,
        input_field: str = "body.features",
        output_property: str = "ml_prediction",
        model_type: str | None = None,
        fallback_on_error: bool = True,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"ml_predict:{model_endpoint}")
        self._model_endpoint = model_endpoint
        self._input_field = input_field
        self._output_property = output_property
        self._model_type = model_type
        self._fallback_on_error = fallback_on_error
        self._loader: Any = None  # lazily set

    def _get_loader(self) -> Any:
        """Lazy-инициализация MLModelLoader (singleton через модуль)."""
        if self._loader is None:
            from src.backend.services.ai.ml.model_loader import get_ml_model_loader

            # Глобальный singleton с LRU=8 моделей
            self._loader = get_ml_model_loader()
        return self._loader

    async def _resolve_artifact_uri(self) -> str | None:
        """Находит путь к бинарному файлу модели через LocalFSModelRegistry (async)."""
        # Кэшируем результат чтобы не ходить в registry каждый раз
        cached = getattr(self, "_cached_artifact_uri", None)
        if cached is not None:
            return cached

        try:
            from src.backend.services.ai.model_registry import LocalFSModelRegistry

            registry = LocalFSModelRegistry()
            record = await registry.get_model(self._model_endpoint)
            result = record.artifact_uri if record else None
            # Кэшируем
            object.__setattr__(self, "_cached_artifact_uri", result)
            return result
        except Exception as exc:  # noqa: BLE001
            _logger.debug("LocalFSModelRegistry lookup failed: %s", exc)
            object.__setattr__(self, "_cached_artifact_uri", None)
        return None

    def _extract_input(self, exchange: Exchange[Any]) -> Any:
        """Извлекает входной тензор/массив из exchange по dotted-path."""
        body = exchange.in_message.body
        if not isinstance(body, dict):
            # Если body — не dict, используем как есть (например, list[float])
            return body

        # Разбор dotted-path: "body.features" → идём в body["features"]
        parts = self._input_field.split(".", 1)
        # parts[0] может быть "body" или "properties"
        if len(parts) == 1:
            key = parts[0]
        else:
            key = parts[1] if parts[0] in ("body", "properties") else parts[0]

        # Пробуем пройти по вложенным ключам
        value = body
        for k in key.split("."):
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return value
        return value

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Выполняет ML-инференс."""
        del context  # Зарезервирован для будущего use (correlation, tenant_id)
        # 1. Найти artifact URI модели
        artifact_uri = await self._resolve_artifact_uri()
        if artifact_uri is None:
            msg = f"Model '{self._model_endpoint}' not found in LocalFSModelRegistry"
            if self._fallback_on_error:
                _logger.warning(msg)
                exchange.set_property(self._output_property, None)
                return
            exchange.fail(msg)
            return

        # 2. Извлечь входные данные
        import numpy as np

        input_data = self._extract_input(exchange)
        if input_data is None:
            msg = f"Input field '{self._input_field}' not found in message body"
            if self._fallback_on_error:
                _logger.warning(msg)
                exchange.set_property(self._output_property, None)
                return
            exchange.fail(msg)
            return

        # 3. Загрузить модель (lazy, с LRU-кэшированием)
        loader = self._get_loader()
        try:
            model = await loader.load(artifact_uri, model_type=self._model_type)
        except Exception as exc:
            msg = f"Failed to load model {self._model_endpoint}: {exc}"
            if self._fallback_on_error:
                _logger.warning(msg)
                exchange.set_property(self._output_property, None)
                return
            exchange.fail(msg)
            return

        # 4. Инференс
        try:
            arr = np.array(input_data, dtype=np.float32)

            # torch model
            if hasattr(model, "eval"):
                import torch

                with torch.no_grad():
                    tensor = torch.from_numpy(arr)
                    if tensor.ndim == 1:
                        tensor = tensor.unsqueeze(0)
                    output = model(tensor)
                    prediction = (
                        output.squeeze().tolist()
                        if hasattr(output, "squeeze")
                        else list(output)
                    )
            # ONNX session
            elif hasattr(model, "run"):
                input_name = model.get_inputs()[0].name
                outputs = model.run(None, {input_name: arr})
                prediction = outputs[0].tolist()
            # sklearn / catboost / lightgbm (все имеют метод predict)
            elif hasattr(model, "predict"):
                prediction = model.predict(input_data)
                if hasattr(prediction, "tolist"):
                    prediction = prediction.tolist()
            else:
                raise RuntimeError(
                    f"Loaded model type not supported for inference: {type(model)}"
                )

            exchange.set_property(self._output_property, prediction)

        except Exception as exc:
            msg = f"ML inference failed for {self._model_endpoint}: {exc}"
            if self._fallback_on_error:
                _logger.warning(msg)
                exchange.set_property(self._output_property, None)
                return
            exchange.fail(msg)
