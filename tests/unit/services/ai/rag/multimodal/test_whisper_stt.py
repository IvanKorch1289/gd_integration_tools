"""Тесты Sprint 11 K4 W1 — Whisper STT (mock)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.backend.services.ai.rag.multimodal.whisper_stt import (
    TranscriptionResult,
    WhisperSTT,
)


@pytest.mark.asyncio
async def test_whisper_loads_and_transcribes() -> None:
    """Mock-модель → text+language+segments извлекаются корректно."""
    stt = WhisperSTT(model_name="mock-base", language="ru")
    fake_model = MagicMock()
    fake_model.transcribe.return_value = {
        "text": " Привет мир ",
        "language": "ru",
        "segments": [{"start": 0.0, "end": 1.2, "text": "Привет мир"}],
    }
    stt._model = fake_model

    result = await stt.transcribe(b"FAKEWAV", suffix=".wav")
    assert isinstance(result, TranscriptionResult)
    assert result.text == "Привет мир"
    assert result.language == "ru"
    assert len(result.segments) == 1
    assert result.model == "mock-base"


def test_whisper_load_raises_without_package(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без openai-whisper _load() даёт RuntimeError с указанием extra."""
    stt = WhisperSTT(model_name="tiny")

    import builtins

    real_import = builtins.__import__

    def _fail(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "whisper":
            raise ImportError("No module named 'whisper'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fail)
    with pytest.raises(RuntimeError) as exc:
        stt._load()
    assert "ai-voice" in str(exc.value)
