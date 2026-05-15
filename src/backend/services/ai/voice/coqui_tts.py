"""CoquiTTSService — text-to-speech поверх Coqui ``TTS`` (K4 S7).

Назначение:
    Тонкий async-wrapper над ``TTS.api.TTS.tts_to_file()`` / ``tts()``.
    Lazy-import ``TTS`` — отсутствие пакета не ломает импорт модуля.

Capabilities (V11.1):
    Сервис декларирует capability вида ``voice.tts.<provider>``
    (default provider — ``"coqui"``). Capability-gate (если передан)
    вызывается перед каждым :meth:`synthesize` для аудит-трейла.

Активация:
    ``feature_flags.voice_stt_tts_enabled`` (default-OFF). При выключенном
    флаге :meth:`synthesize` поднимает :class:`VoiceServiceUnavailable`.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.backend.services.ai.voice.whisper_stt import VoiceServiceUnavailable

__all__ = ("CoquiTTSService", "TTSResult")

logger = logging.getLogger(__name__)

# Default-модель Coqui для русского + многоязычная.
DEFAULT_COQUI_MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"


@dataclass(slots=True)
class TTSResult:
    """Результат :meth:`CoquiTTSService.synthesize`.

    Attributes:
        output_path: Путь к синтезированному WAV-файлу.
        language: Код языка синтеза (``"ru"``, ``"en"``).
        provider: Имя провайдера (``"coqui"``).
        model: Идентификатор использованной модели.
        sample_rate: Частота дискретизации (Hz), если известна.
    """

    output_path: Path
    language: str = "ru"
    provider: str = "coqui"
    model: str = ""
    sample_rate: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_path": str(self.output_path),
            "language": self.language,
            "provider": self.provider,
            "model": self.model,
            "sample_rate": int(self.sample_rate),
        }


class CoquiTTSService:
    """Async-обёртка над Coqui ``TTS.api.TTS`` для TTS.

    Args:
        model_name: Идентификатор модели Coqui TTS. default — XTTS v2.
        provider: Имя провайдера для capability (``"coqui"`` по умолчанию).
        progress_bar: Показывать прогресс-бар при загрузке модели.
        gpu: Использовать GPU (``True``) или CPU (``False``).
        capability_audit: Опциональный callable, принимающий
            ``(capability_name, model)`` — вызывается перед каждым
            :meth:`synthesize` для аудит-трейла.
        enabled: Override feature-flag (для тестов).

    Examples:
        >>> svc = CoquiTTSService()
        >>> if svc.is_available():
        ...     result = await svc.synthesize("Привет, мир", lang="ru")
        ...     print(result.output_path)
    """

    def __init__(
        self,
        *,
        model_name: str = DEFAULT_COQUI_MODEL,
        provider: str = "coqui",
        progress_bar: bool = False,
        gpu: bool = False,
        capability_audit: Any = None,
        enabled: bool | None = None,
    ) -> None:
        self._model_name = model_name
        self._provider = provider
        self._progress_bar = progress_bar
        self._gpu = gpu
        self._capability_audit = capability_audit
        self._enabled_override = enabled
        self._tts_module: Any = None
        self._engine: Any = None

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def capability(self) -> str:
        """Capability-имя для V11.1 capability-gate (``voice.tts.<provider>``)."""
        return f"voice.tts.{self._provider}"

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
        """True если установлен ``TTS`` и feature-flag включён."""
        if not self.enabled:
            return False
        try:
            from TTS.api import TTS  # type: ignore[import-not-found]  # noqa: F401

            return True
        except ImportError:
            return False

    def _ensure_engine(self) -> Any:
        """Lazy-import ``TTS.api.TTS`` + lazy-load выбранной модели."""
        if self._engine is not None:
            return self._engine
        if not self.enabled:
            raise VoiceServiceUnavailable(
                "CoquiTTSService отключён (voice_stt_tts_enabled=false)."
            )
        try:
            from TTS.api import TTS  # type: ignore[import-not-found]
        except ImportError as exc:
            raise VoiceServiceUnavailable(
                "Пакет 'TTS' не установлен — добавьте extra '[ai-voice]'."
            ) from exc

        try:
            self._engine = TTS(
                model_name=self._model_name,
                progress_bar=self._progress_bar,
                gpu=self._gpu,
            )
        except Exception as exc:  # noqa: BLE001
            raise VoiceServiceUnavailable(
                f"Не удалось загрузить Coqui-модель '{self._model_name}': {exc}"
            ) from exc
        return self._engine

    async def synthesize(
        self,
        text: str,
        *,
        lang: str = "ru",
        output_path: str | Path | None = None,
        speaker: str | None = None,
        speaker_wav: str | Path | None = None,
        **kwargs: Any,
    ) -> TTSResult:
        """Синтезирует речь из текста и сохраняет в WAV-файл.

        Args:
            text: Текст для синтеза (UTF-8).
            lang: Код языка (``"ru"``, ``"en"``, ``"de"`` ...). default=``"ru"``.
            output_path: Целевой путь WAV-файла. При ``None`` создаётся
                временный файл (вызывающий код отвечает за его удаление).
            speaker: Имя preset-голоса (для multi-speaker моделей).
            speaker_wav: Reference WAV-файл для voice cloning (XTTS).
            **kwargs: Дополнительные параметры ``TTS.tts_to_file()``.

        Returns:
            :class:`TTSResult` с путём к WAV-файлу и метаданными.

        Raises:
            VoiceServiceUnavailable: SDK не установлен / flag выключен.
            ValueError: пустой ``text``.
        """
        if not text or not text.strip():
            raise ValueError("CoquiTTSService.synthesize: пустой текст")

        # Capability-audit hook (V11.1) — best-effort.
        if self._capability_audit is not None:
            try:
                self._capability_audit(self.capability, self._model_name)
            except Exception as exc:  # noqa: BLE001
                logger.debug("capability_audit hook failed: %s", exc)

        engine = self._ensure_engine()

        if output_path is None:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                target = Path(tmp.name)
        else:
            target = Path(output_path)
            target.parent.mkdir(parents=True, exist_ok=True)

        tts_kwargs: dict[str, Any] = {
            "text": text,
            "file_path": str(target),
            "language": lang,
            **kwargs,
        }
        if speaker is not None:
            tts_kwargs["speaker"] = speaker
        if speaker_wav is not None:
            tts_kwargs["speaker_wav"] = str(speaker_wav)

        try:
            await asyncio.to_thread(engine.tts_to_file, **tts_kwargs)
        except Exception as exc:  # noqa: BLE001
            raise VoiceServiceUnavailable(f"Coqui tts_to_file failed: {exc}") from exc

        sample_rate = self._extract_sample_rate(engine)
        return TTSResult(
            output_path=target,
            language=lang,
            provider=self._provider,
            model=self._model_name,
            sample_rate=sample_rate,
        )

    @staticmethod
    def _extract_sample_rate(engine: Any) -> int:
        """Извлекает sample_rate из synthesizer.output_sample_rate (best-effort)."""
        synthesizer = getattr(engine, "synthesizer", None)
        if synthesizer is not None:
            rate = getattr(synthesizer, "output_sample_rate", None)
            if isinstance(rate, int):
                return rate
        return 0
