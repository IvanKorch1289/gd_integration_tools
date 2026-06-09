"""BLIP2 image captioner (Sprint 11 K4 W1).

Lazy-import transformers/BLIP2 — heavy ML stack (~5GB веса) включается
только при первом вызове ``caption()``. Без extras ``[multimodal-rag]``
конструктор возвращает no-op fallback (``caption()`` бросает RuntimeError).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.backend.core.logging import get_logger

__all__ = ("BLIP2Captioner", "CaptionResult")

logger = get_logger("services.ai.rag.multimodal.blip2")


@dataclass(frozen=True, slots=True)
class CaptionResult:
    """Результат captioning одного изображения.

    Attributes:
        caption: Сгенерированный текст описания.
        model: Имя HF модели, использованной для inference.
        device: Куда загрузили модель (cpu/cuda/mps).
    """

    caption: str
    model: str
    device: str


class BLIP2Captioner:
    """Async-обёртка над BLIP2 captioning через HuggingFace transformers.

    Args:
        model_name: HF model id, по умолчанию
            ``Salesforce/blip2-opt-2.7b`` (минимальный production-ready
            вариант). Можно подставить меньший mock для CI.
        device: ``cpu`` / ``cuda`` / ``mps``. По умолчанию ``cpu`` —
            безопасный fallback. Реальные GPU-runners сами выберут cuda.
    """

    def __init__(
        self, model_name: str = "Salesforce/blip2-opt-2.7b", device: str = "cpu"
    ) -> None:
        self._model_name = model_name
        self._device = device
        self._processor: Any = None
        self._model: Any = None

    def _load(self) -> None:
        """Lazy-инициализация: тянет transformers только при первом вызове."""
        if self._model is not None:
            return
        try:
            from transformers import (  # type: ignore[import-not-found]
                AutoProcessor,
                Blip2ForConditionalGeneration,
            )
        except ImportError as exc:
            raise RuntimeError(
                "BLIP2 requires `pip install gd_advanced_tools[multimodal-rag]`"
                f" (transformers): {exc}"
            ) from exc

        logger.info(
            "BLIP2Captioner loading model=%s device=%s", self._model_name, self._device
        )
        self._processor = AutoProcessor.from_pretrained(self._model_name)
        self._model = Blip2ForConditionalGeneration.from_pretrained(self._model_name)
        if hasattr(self._model, "to"):
            self._model = self._model.to(self._device)

    async def caption(
        self, image_bytes: bytes, *, max_new_tokens: int = 50
    ) -> CaptionResult:
        """Сгенерировать caption для изображения.

        Args:
            image_bytes: Содержимое файла изображения (jpg/png/webp).
            max_new_tokens: Лимит длины генерации.

        Returns:
            :class:`CaptionResult`.

        Raises:
            RuntimeError: Если transformers/torch не установлены и нет
                fallback'а для текущего окружения.
        """
        self._load()

        # PIL импортируется лениво — он входит в transformers transitive deps.
        from io import BytesIO

        try:
            from PIL import Image
        except ImportError as exc:
            raise RuntimeError(
                "BLIP2 requires Pillow — install [multimodal-rag] extra"
            ) from exc

        image = Image.open(BytesIO(image_bytes)).convert("RGB")
        inputs = self._processor(images=image, return_tensors="pt")
        if self._device != "cpu":
            inputs = {k: v.to(self._device) for k, v in inputs.items()}
        generated = self._model.generate(**inputs, max_new_tokens=max_new_tokens)
        caption = self._processor.batch_decode(generated, skip_special_tokens=True)[
            0
        ].strip()
        return CaptionResult(
            caption=caption, model=self._model_name, device=self._device
        )
