"""Unit-тесты WhisperSTTService (K4 Sprint 7).

Покрывают:
1. default-OFF: is_available() возвращает False при выключенном flag.
2. Lazy-import: при отсутствии 'whisper' → VoiceServiceUnavailable.
3. transcribe() с mock-моделью возвращает корректный STTResult.
4. FileNotFoundError для несуществующего пути.
5. Capability-name формат ``voice.stt.<provider>``.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from src.backend.services.ai.voice import (
    STTResult,
    VoiceServiceUnavailable,
    WhisperSTTService,
)


def test_is_available_returns_false_when_flag_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При выключенном feature_flag is_available() == False даже если SDK есть."""
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "voice_stt_tts_enabled", False, raising=False)
    svc = WhisperSTTService()
    assert svc.is_available() is False
    assert svc.enabled is False


def test_capability_name_uses_provider() -> None:
    """capability формируется как ``voice.stt.<provider>``."""
    svc = WhisperSTTService(provider="whisper")
    assert svc.capability == "voice.stt.whisper"

    custom = WhisperSTTService(provider="faster-whisper")
    assert custom.capability == "voice.stt.faster-whisper"


@pytest.mark.asyncio
async def test_transcribe_raises_when_whisper_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """При отсутствии пакета 'whisper' transcribe → VoiceServiceUnavailable."""
    monkeypatch.setitem(sys.modules, "whisper", None)  # форсируем ImportError
    audio = tmp_path / "fake.wav"
    audio.write_bytes(b"RIFF....")

    svc = WhisperSTTService(enabled=True)
    with pytest.raises(VoiceServiceUnavailable, match="openai-whisper"):
        await svc.transcribe(audio)


@pytest.mark.asyncio
async def test_transcribe_returns_result_via_mock_whisper(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """transcribe() с mock-whisper возвращает STTResult с распознанным текстом."""
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"RIFF....data")

    class _FakeModel:
        def transcribe(self, path: str, **kwargs: Any) -> dict[str, Any]:
            assert path == str(audio)
            return {
                "text": "  Привет, мир  ",
                "language": "ru",
                "segments": [
                    {"start": 0.0, "end": 1.5, "text": "Привет,"},
                    {"start": 1.5, "end": 2.7, "text": "мир"},
                ],
            }

    fake_whisper = types.SimpleNamespace(load_model=lambda name, **kw: _FakeModel())
    monkeypatch.setitem(sys.modules, "whisper", fake_whisper)

    audited: list[tuple[str, str]] = []

    def _audit(cap: str, model: str) -> None:
        audited.append((cap, model))

    svc = WhisperSTTService(model_name="base", enabled=True, capability_audit=_audit)
    result = await svc.transcribe(audio, language="ru")

    assert isinstance(result, STTResult)
    assert result.text == "Привет, мир"
    assert result.language == "ru"
    assert result.duration_seconds == pytest.approx(2.7)
    assert result.provider == "whisper"
    assert result.model == "base"
    assert audited == [("voice.stt.whisper", "base")]


@pytest.mark.asyncio
async def test_transcribe_raises_file_not_found(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """transcribe() с несуществующим путём → FileNotFoundError."""
    svc = WhisperSTTService(enabled=True)
    with pytest.raises(FileNotFoundError):
        await svc.transcribe(tmp_path / "missing.wav")
