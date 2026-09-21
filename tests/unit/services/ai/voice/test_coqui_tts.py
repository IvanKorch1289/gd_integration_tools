"""Unit-тесты CoquiTTSService (K4 Sprint 7).

Покрывают:
1. default-OFF: is_available() == False при выключенном flag.
2. Lazy-import: при отсутствии 'TTS' → VoiceServiceUnavailable.
3. synthesize() с mock-engine создаёт WAV и возвращает TTSResult.
4. Пустой text → ValueError; capability формат ``voice.tts.<provider>``.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest

from src.backend.services.ai.voice import (
    CoquiTTSService,
    TTSResult,
    VoiceServiceUnavailable,
)


def test_is_available_false_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """is_available() возвращает False при выключенном feature_flag."""
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "voice_stt_tts_enabled", False, raising=False)
    svc = CoquiTTSService()
    assert svc.is_available() is False


def test_capability_and_empty_text() -> None:
    """capability формат ``voice.tts.<provider>``; пустой текст → ValueError."""
    svc = CoquiTTSService(provider="coqui", enabled=True)
    assert svc.capability == "voice.tts.coqui"

    import asyncio

    with pytest.raises(ValueError, match="пустой текст"):
        asyncio.run(svc.synthesize("   "))


@pytest.mark.asyncio
async def test_synthesize_raises_when_tts_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При отсутствии 'TTS' synthesize() → VoiceServiceUnavailable."""

    # Подсовываем TTS-пакет с api-модулем, который ImportError.
    fake_pkg = types.ModuleType("TTS")
    monkeypatch.setitem(sys.modules, "TTS", fake_pkg)
    monkeypatch.setitem(sys.modules, "TTS.api", None)

    svc = CoquiTTSService(enabled=True)
    with pytest.raises(VoiceServiceUnavailable, match="'TTS'"):
        await svc.synthesize("Привет", lang="ru")


@pytest.mark.asyncio
async def test_synthesize_writes_wav_via_mock_engine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """synthesize() с mock TTS-engine создаёт WAV-файл и возвращает TTSResult."""
    output = tmp_path / "out.wav"
    calls: list[dict[str, Any]] = []

    class _FakeEngine:
        synthesizer = types.SimpleNamespace(output_sample_rate=22050)

        def tts_to_file(self, **kwargs: Any) -> str:
            calls.append(kwargs)
            Path(kwargs["file_path"]).write_bytes(b"RIFFWAV")
            return kwargs["file_path"]

    fake_tts_module = types.ModuleType("TTS")
    fake_api_module = types.ModuleType("TTS.api")
    fake_api_module.TTS = lambda **kw: _FakeEngine()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "TTS", fake_tts_module)
    monkeypatch.setitem(sys.modules, "TTS.api", fake_api_module)

    audited: list[tuple[str, str]] = []
    svc = CoquiTTSService(
        model_name="tts_models/multilingual/multi-dataset/xtts_v2",
        enabled=True,
        capability_audit=lambda cap, model: audited.append((cap, model)),
    )

    result = await svc.synthesize(
        "Привет, мир", lang="ru", output_path=output, speaker_wav=tmp_path / "ref.wav"
    )

    assert isinstance(result, TTSResult)
    assert result.output_path == output
    assert output.exists()
    assert result.language == "ru"
    assert result.provider == "coqui"
    assert result.sample_rate == 22050
    assert audited and audited[0][0] == "voice.tts.coqui"
    assert calls[0]["text"] == "Привет, мир"
    assert calls[0]["language"] == "ru"
    assert calls[0]["speaker_wav"].endswith("ref.wav")
