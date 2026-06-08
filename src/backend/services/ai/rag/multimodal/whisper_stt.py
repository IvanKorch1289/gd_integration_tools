"""Whisper STT — speech-to-text для audio модальности (Sprint 11 K4 W1).

Lazy-import openai-whisper + librosa (resample 16kHz mono). Без extras
``[ai-voice]`` / ``[multimodal-rag]`` конструктор работает в no-op режиме —
``transcribe()`` бросает RuntimeError.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from typing import Any

from src.backend.infrastructure.logging.factory import get_logger

__all__ = ("WhisperSTT", "TranscriptionResult")

logger = get_logger("services.ai.rag.multimodal.whisper")


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    """Результат STT одной аудиозаписи.

    Attributes:
        text: Полный transcript.
        language: Код языка из detect (ISO 639-1).
        segments: Список ``{start, end, text}`` фрагментов.
        model: Имя whisper модели.
    """

    text: str
    language: str
    segments: list[dict[str, Any]]
    model: str


class WhisperSTT:
    """Async-обёртка над OpenAI Whisper STT.

    Args:
        model_name: ``tiny``/``base``/``small``/``medium``/``large``/``large-v3``.
            По умолчанию ``base`` — компромисс скорость/качество.
        language: Опционально явный язык (``ru``, ``en``, ...). Если ``None`` —
            whisper определит автоматически.
    """

    def __init__(self, model_name: str = "base", language: str | None = None) -> None:
        self._model_name = model_name
        self._language = language
        self._model: Any = None

    def _load(self) -> None:
        """Lazy-инициализация: тянет openai-whisper при первом вызове."""
        if self._model is not None:
            return
        try:
            import whisper  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "Whisper STT requires `pip install gd_advanced_tools[ai-voice]`"
                f" (openai-whisper): {exc}"
            ) from exc

        logger.info("WhisperSTT loading model=%s", self._model_name)
        self._model = whisper.load_model(self._model_name)

    async def transcribe(
        self, audio_bytes: bytes, *, suffix: str = ".wav"
    ) -> TranscriptionResult:
        """Расшифровать аудиозапись в текст.

        Args:
            audio_bytes: Содержимое аудиофайла (wav/mp3/m4a/flac).
            suffix: Расширение файла для tempfile (по умолчанию .wav).

        Returns:
            :class:`TranscriptionResult` с text/language/segments.
        """
        self._load()

        # Whisper принимает path или numpy array; пишем во временный файл
        # для совместимости с любыми форматами через ffmpeg fallback.
        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name

            options: dict[str, Any] = {"fp16": False}
            if self._language is not None:
                options["language"] = self._language
            result = self._model.transcribe(tmp_path, **options)
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        return TranscriptionResult(
            text=str(result.get("text", "")).strip(),
            language=str(result.get("language") or self._language or ""),
            segments=list(result.get("segments") or []),
            model=self._model_name,
        )
