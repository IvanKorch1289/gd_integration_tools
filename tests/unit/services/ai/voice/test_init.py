"""Unit-тесты ``services.ai.voice`` — coverage ratchet (Post-Plan A Sprint 12).

core/ai/voice service package facade (K4 S7 + V11.1): re-exports 4 symbols
(CoquiTTSService, STTResult, VoiceServiceUnavailable, WhisperSTTService).
~8 stmts, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + class identity.
"""

from __future__ import annotations

import pytest

from src.backend.services.ai import voice
from src.backend.services.ai.voice import (
    CoquiTTSService,
    STTResult,
    TTSResult,
    VoiceServiceUnavailable,
    WhisperSTTService,
)


@pytest.mark.unit
class TestVoiceFacadeAllExports:
    """``__all__`` audit + class identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        [
            "CoquiTTSService",
            "STTResult",
            "TTSResult",
            "VoiceServiceUnavailable",
            "WhisperSTTService",
        ],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(voice, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in voice.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 5 символов."""
        assert len(voice.__all__) == 5

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает voice services (K4 S7 + V11.1)."""
        assert voice.__doc__ is not None
        assert "Voice" in voice.__doc__ or "STT" in voice.__doc__ or "TTS" in voice.__doc__


@pytest.mark.unit
class TestVoiceFacadeIdentity:
    """Identity checks для 4 re-exports."""

    def test_whisper_stt_service_is_class(self) -> None:
        """``WhisperSTTService`` — class (speech-to-text)."""
        assert isinstance(WhisperSTTService, type)

    def test_coqui_tts_service_is_class(self) -> None:
        """``CoquiTTSService`` — class (text-to-speech)."""
        assert isinstance(CoquiTTSService, type)

    def test_stt_result_is_class(self) -> None:
        """``STTResult`` — class (result dataclass)."""
        assert isinstance(STTResult, type)

    def test_tts_result_is_class(self) -> None:
        """``TTSResult`` — class (result dataclass)."""
        assert isinstance(TTSResult, type)

    def test_voice_service_unavailable_is_exception(self) -> None:
        """``VoiceServiceUnavailable`` — Exception subclass."""
        assert isinstance(VoiceServiceUnavailable, type)
        assert issubclass(VoiceServiceUnavailable, Exception)
