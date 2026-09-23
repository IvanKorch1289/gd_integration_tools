"""Voice-сервисы К4 S7: Whisper STT + Coqui TTS (lazy-import).

Реализуют:
    * :class:`WhisperSTTService` — speech-to-text через ``openai-whisper``;
    * :class:`CoquiTTSService` — text-to-speech через ``TTS`` (Coqui).

Активация: feature_flag ``voice_stt_tts_enabled`` (default-OFF).
Capabilities (V11.1): ``voice.stt.<provider>``, ``voice.tts.<provider>``.

Тяжёлые SDK (``whisper``, ``TTS.api.TTS``) импортируются по требованию;
при отсутствии extras :meth:`is_available` возвращает ``False``,
а :meth:`transcribe` / :meth:`synthesize` поднимают
:class:`VoiceServiceUnavailable`.
"""

from src.backend.services.ai.voice.coqui_tts import CoquiTTSService, TTSResult
from src.backend.services.ai.voice.whisper_stt import (
    STTResult,
    VoiceServiceUnavailable,
    WhisperSTTService,
)

__all__ = (
    "CoquiTTSService",
    "STTResult",
    "TTSResult",
    "VoiceServiceUnavailable",
    "WhisperSTTService",
)
