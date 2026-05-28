"""ML Model Loader Protocol — контракт для загрузки ML-моделей.

Wave: ``[wave:s29/local-models-repository]``.

Этот Protocol находится в ``core/`` чтобы обеспечить layer separation:
dsl/ и services/ зависят от абстракции, а implementation в services/ai/ml/.

Реализация:
- :class:`MLModelLoader` в ``services.ai.ml.model_loader``
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

from typing_extensions import TypeAlias

if TYPE_CHECKING:
    pass

__all__ = ("MLModelLoaderProtocol", "MLModelType")

MLModelType: TypeAlias = Literal["torch", "torchscript", "onnx", "sklearn", "catboost", "lightgbm", "joblib"]


@runtime_checkable
class MLModelLoaderProtocol(Protocol):
    """Контракт универсального загрузчика ML-моделей.

    Все методы lazy — реализации могут блокировать на загрузке тяжёлых
    библиотек или модели; вызывающий код должен оборачивать в executor
    если реализация синхронная.
    """

    async def load(
        self,
        path: str | Path,
        model_type: MLModelType | None = None,
    ) -> Any:
        """Загружает модель (lazy, с LRU-кэшированием).

        Args:
            path: Путь к файлу модели.
            model_type: Тип модели. Если ``None`` — определяется по расширению.

        Returns:
            Загруженный модельный объект.

        Raises:
            RuntimeError: Если библиотека не установлена или тип неизвестен.
        """
        ...

    def unload(self, path: str | Path) -> None:
        """Удаляет модель из кэша (освобождает память)."""
        ...