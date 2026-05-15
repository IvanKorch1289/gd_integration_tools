"""WhisperSTTService — speech-to-text поверх ``openai-whisper`` (K4 S7).

Назначение:
    Тонкий async-wrapper над ``whisper.load_model() + model.transcribe()``.
    Lazy-import ``whisper`` — отсутствие пакета не ломает импорт модуля.

Capabilities (V11.1):
    Сервис декларирует capability вида ``voice.stt.<provider>``
    (default provider — ``"whisper"``). Capability-gate (если передан)
    вызывается перед каждым :meth:`transcribe` для аудит-трейла.

Активация:
    ``feature_flags.voice_stt_tts_enabled`` (default-OFF). При выключенном
    флаге :meth:`transcribe` поднимает :class:`VoiceServiceUnavailable`.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = ("STTResult", "VoiceServiceUnavailable", "WhisperSTTService")

logger = logging.getLogger(__name__)


class VoiceServiceUnavailable(RuntimeError):
    """Voice SDK не установлен, feature-flag выключен или модель не загрузилась."""


@dataclass(slots=True)
class STTResult:
    """Результат :meth:`WhisperSTTService.transcribe`.

    Attributes:
        text: Распознанный текст (UTF-8).
        language: BCP-47-подобный код языка (``"ru"``, ``"en"``, ...).
        segments: Сегменты Whisper (start, end, text) — для тайм-кодов.
        duration_seconds: Длительность аудио в секундах (если известно).
        provider: Имя провайдера (``"whisper"``).
        model: Идентификатор использованной модели.
    """

    text: str
    language: str = ""
    segments: list[dict[str, Any]] = field(default_factory=list)
    duration_seconds: float = 0.0
    provider: str = "whisper"
    model: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "language": self.language,
            "segments": list(self.segments),
            "duration_seconds": float(self.duration_seconds),
            "provider": self.provider,
            "model": self.model,
        }


class WhisperSTTService:
    """Async-обёртка над ``openai-whisper`` для STT.

    Args:
        model_name: Идентификатор Whisper-модели (``"tiny"``, ``"base"``,
            ``"small"``, ``"medium"``, ``"large-v3"``, ...). default=``"base"``.
        provider: Имя провайдера для capability (``"whisper"`` по умолчанию).
        device: Опциональный device-hint (``"cpu"``, ``"cuda"``).
        capability_audit: Опциональный callable, принимающий
            ``(capability_name, model)`` — вызывается перед каждым
            :meth:`transcribe` для аудит-трейла (см.
            :mod:`core.security.capabilities`).
        enabled: Override feature-flag (для тестов). При None — читается
            из ``feature_flags.voice_stt_tts_enabled``.

    Examples:
        >>> svc = WhisperSTTService(model_name="base")
        >>> if svc.is_available():
        ...     result = await svc.transcribe("audio.wav")
        ...     print(result.text)
    """

    def __init__(
        self,
        *,
        model_name: str = "base",
        provider: str = "whisper",
        device: str | None = None,
        capability_audit: Any = None,
        enabled: bool | None = None,
    ) -> None:
        self._model_name = model_name
        self._provider = provider
        self._device = device
        self._capability_audit = capability_audit
        self._enabled_override = enabled
        self._whisper: Any = None
        self._model: Any = None

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def capability(self) -> str:
        """Capability-имя для V11.1 capability-gate (``voice.stt.<provider>``)."""
        return f"voice.stt.{self._provider}"

    @property
    def enabled(self) -> bool:
        """True если feature-flag активен ИЛИ передан enabled=True в __init__."""
        if self._enabled_override is not None:
            return bool(self._enabled_override)
        try:
            from src.backend.core.config.features import feature_flags

            return bool(getattr(feature_flags, "voice_stt_tts_enabled", False))
        except Exception:  # noqa: BLE001
            return False

    def is_available(self) -> bool:
        """True если установлен ``whisper`` и feature-flag включён."""
        if not self.enabled:
            return False
        try:
            import whisper  # type: ignore[import-not-found]  # noqa: F401

            return True
        except ImportError:
            return False

    def _ensure_whisper(self) -> Any:
        """Lazy-import ``whisper``. Поднимает :class:`VoiceServiceUnavailable`."""
        if self._whisper is not None:
            return self._whisper
        if not self.enabled:
            raise VoiceServiceUnavailable(
                "WhisperSTTService отключён (voice_stt_tts_enabled=false)."
            )
        try:
            import whisper  # type: ignore[import-not-found]
        except ImportError as exc:
            raise VoiceServiceUnavailable(
                "Пакет 'openai-whisper' не установлен — добавьте extra '[ai-voice]'."
            ) from exc
        self._whisper = whisper
        return whisper

    def _ensure_model(self) -> Any:
        """Lazy-load Whisper-модели через ``whisper.load_model()``."""
        if self._model is not None:
            return self._model
        whisper = self._ensure_whisper()
        try:
            kwargs: dict[str, Any] = {}
            if self._device is not None:
                kwargs["device"] = self._device
            self._model = whisper.load_model(self._model_name, **kwargs)
        except Exception as exc:  # noqa: BLE001
            raise VoiceServiceUnavailable(
                f"Не удалось загрузить Whisper-модель '{self._model_name}': {exc}"
            ) from exc
        return self._model

    async def transcribe(
        self,
        audio_path: str | Path,
        *,
        language: str | None = None,
        task: str = "transcribe",
        **kwargs: Any,
    ) -> STTResult:
        """Распознаёт речь из аудио-файла.

        Args:
            audio_path: Путь к аудио-файлу (wav/mp3/m4a/ogg, любой
                поддерживаемый ffmpeg).
            language: BCP-47-подобный код языка (``"ru"``). При ``None``
                Whisper определяет язык автоматически.
            task: ``"transcribe"`` (default) или ``"translate"`` (перевод на
                английский).
            **kwargs: Дополнительные параметры ``model.transcribe()``
                (``temperature``, ``beam_size``, ``initial_prompt`` и т.п.).

        Returns:
            :class:`STTResult` с распознанным текстом и метаданными.

        Raises:
            VoiceServiceUnavailable: SDK не установлен / flag выключен /
                модель не загрузилась.
            FileNotFoundError: Аудио-файл не существует.
        """
        path = Path(audio_path)
        if not path.exists():
            raise FileNotFoundError(f"Аудио-файл не найден: {path}")

        # Capability-audit hook (V11.1) — best-effort, не ломает вызов.
        if self._capability_audit is not None:
            try:
                self._capability_audit(self.capability, self._model_name)
            except Exception as exc:  # noqa: BLE001
                logger.debug("capability_audit hook failed: %s", exc)

        model = self._ensure_model()
        transcribe_kwargs: dict[str, Any] = {"task": task, **kwargs}
        if language is not None:
            transcribe_kwargs["language"] = language

        try:
            response: Any = await asyncio.to_thread(
                model.transcribe, str(path), **transcribe_kwargs
            )
        except Exception as exc:  # noqa: BLE001
            raise VoiceServiceUnavailable(f"Whisper transcribe failed: {exc}") from exc

        return self._build_result(response)

    def _build_result(self, response: Any) -> STTResult:
        """Нормализует ответ ``whisper.transcribe`` в :class:`STTResult`."""
        payload: dict[str, Any] = response if isinstance(response, dict) else {}
        text = str(payload.get("text", "")).strip()
        language = str(payload.get("language", "") or "")
        segments_raw = payload.get("segments") or []
        segments: list[dict[str, Any]] = []
        duration = 0.0
        for seg in segments_raw:
            if isinstance(seg, dict):
                segments.append(dict(seg))
                end_value = seg.get("end")
                if isinstance(end_value, (int, float)):
                    duration = max(duration, float(end_value))
        return STTResult(
            text=text,
            language=language,
            segments=segments,
            duration_seconds=duration,
            provider=self._provider,
            model=self._model_name,
        )
