"""Embedders для MultimodalRAG: CLIP (text+image) и colpali (документ-уровень).

``CLIPEmbedder`` — обёртка над ``sentence-transformers`` (модель
``clip-ViT-B-32``); поддерживает текст (str) и изображения (bytes).
``ColpaliEmbedder`` — заглушка над ``colpali_engine`` (document-level
retrieval). При отсутствии ML-зависимостей оба embedder'а поднимают
``LazyImportError`` при первом вызове, не на import-time.

Lazy-import гарантирует, что unit-тесты без torch/sentence-transformers
не падают на коллекции.
"""

from __future__ import annotations
from src.backend.infrastructure.logging.factory import get_logger

import asyncio
import io

from typing import Any

logger = get_logger(__name__)

__all__ = ("CLIPEmbedder", "ColpaliEmbedder", "LazyImportError")


class LazyImportError(ImportError):
    """Поднимается, если ML-зависимость не установлена на момент вызова.

    Сообщение содержит инструкцию по установке нужного extras-блока
    (``pip install gd_advanced_tools[multimodal-rag]``).
    """


class CLIPEmbedder:
    """CLIP-embedder поверх sentence-transformers.

    Модель по умолчанию — ``clip-ViT-B-32`` (512-dim, text+image).
    Загружается lazy при первом вызове ``embed``, чтобы не блокировать
    startup и unit-тесты без torch.

    Attributes:
        embedding_kind: Идентификатор реализации (``clip``).
        model_name: Имя модели sentence-transformers.
        device: Целевое устройство (``cpu`` / ``cuda``).
    """

    embedding_kind = "clip"

    def __init__(
        self, *, model_name: str = "clip-ViT-B-32", device: str = "cpu"
    ) -> None:
        """Инициализирует CLIPEmbedder (без загрузки модели).

        Args:
            model_name: Имя модели sentence-transformers.
            device: Устройство — ``cpu`` или ``cuda``.
        """
        self.model_name = model_name
        self.device = device
        self._model: Any | None = None

    async def embed(self, content: str | bytes) -> list[float]:
        """Возвращает 512-dim CLIP embedding.

        Args:
            content: Текст (str) или image bytes (PNG/JPEG/WebP).

        Returns:
            Список float фиксированной размерности модели CLIP.

        Raises:
            LazyImportError: Если sentence-transformers/PIL/torch не установлены.
            ValueError: Если content имеет неподдерживаемый тип.
        """
        model = await self._get_model()
        return await asyncio.to_thread(self._encode_sync, model, content)

    async def _get_model(self) -> Any:
        """Lazy-загрузка SentenceTransformer (cached singleton на инстанс)."""
        if self._model is not None:
            return self._model

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise LazyImportError(
                "sentence-transformers не установлен. "
                "Установите extras: pip install gd_advanced_tools[multimodal-rag]"
            ) from exc

        self._model = await asyncio.to_thread(
            SentenceTransformer, self.model_name, device=self.device
        )
        return self._model

    def _encode_sync(self, model: Any, content: str | bytes) -> list[float]:
        """Sync-энкодинг текста/изображения через SentenceTransformer.

        Args:
            model: Загруженная модель.
            content: Текст или image bytes.

        Returns:
            Эмбеддинг как list[float].

        Raises:
            ValueError: Если bytes не парсятся как изображение.
        """
        if isinstance(content, str):
            vec = model.encode(content, convert_to_numpy=True)
        elif isinstance(content, (bytes, bytearray)):
            try:
                from PIL import Image
            except ImportError as exc:
                raise LazyImportError(
                    "Pillow не установлен — обработка изображений недоступна."
                ) from exc

            try:
                img = Image.open(io.BytesIO(content))
                img.load()
            except Exception as exc:  # noqa: BLE001
                raise ValueError(f"не удалось распарсить изображение: {exc}") from exc
            vec = model.encode(img, convert_to_numpy=True)
        else:
            raise ValueError(
                f"CLIPEmbedder: неподдерживаемый тип content={type(content)!r}"
            )

        return [float(x) for x in vec.flatten().tolist()]


class ColpaliEmbedder:
    """Document-level embedder поверх colpali_engine (заглушка).

    Colpali — поздний interaction model для document retrieval (визуально-
    языковая модель для PDF-документов). Поскольку colpali_engine требует
    torch + накладывает значительный вес, реализация — заглушка-крючок:
    при первом ``embed`` пытается импортировать модуль; при отсутствии
    поднимает ``LazyImportError``.

    Attributes:
        embedding_kind: Идентификатор реализации (``colpali``).
        model_name: Имя модели colpali.
    """

    embedding_kind = "colpali"

    def __init__(self, *, model_name: str = "vidore/colpali") -> None:
        """Инициализирует ColpaliEmbedder (без загрузки модели).

        Args:
            model_name: Имя модели colpali_engine.
        """
        self.model_name = model_name
        self._model: Any | None = None

    async def embed(self, content: str | bytes) -> list[float]:
        """Возвращает document-level embedding.

        Args:
            content: Текст или image bytes.

        Returns:
            Эмбеддинг как list[float].

        Raises:
            LazyImportError: Если colpali_engine не установлен.
        """
        try:
            import colpali_engine  # type: ignore[import-not-found]  # noqa: F401
        except ImportError as exc:
            raise LazyImportError(
                "colpali_engine не установлен. "
                "Это опциональная зависимость; включите её отдельно "
                "(colpali-engine>=0.3, требует torch>=2.4)."
            ) from exc

        # NOTE: реальная реализация будет добавлена в Sprint 9 (K4 W5).
        # Заглушка возвращает детерминированный stub-вектор по hash контенту,
        # чтобы тесты могли проверить интеграцию.
        raise LazyImportError(
            "ColpaliEmbedder: production-реализация запланирована на Sprint 9. "
            "Используйте CLIPEmbedder как production-default."
        )
