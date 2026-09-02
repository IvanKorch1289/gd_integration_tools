"""Unit-тесты ``services.ai.ai_providers`` — coverage ratchet (Post-Plan A Sprint 24).

core/ai/ai_providers service package facade (S68 W4 decomp from 443 LOC → 5 files per-provider):
re-exports 5 symbols (ClaudeProvider + GeminiProvider + OllamaProvider +
OpenAIProvider classes + register_extended_providers helper). ~10 stmts, 0%.

Цель slice: 0% → 100% через __all__ audit + class/callable identity.
"""

from __future__ import annotations

import pytest

from src.backend.services.ai import ai_providers
from src.backend.services.ai.ai_providers import (
    ClaudeProvider,
    GeminiProvider,
    GigaChatProvider,
    OllamaProvider,
    OpenAIProvider,
    SaluteSpeechProvider,
    YandexGPTProvider,
    register_extended_providers,
)


@pytest.mark.unit
class TestAiProvidersFacadeAllExports:
    """``__all__`` audit + class/callable identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        [
            "ClaudeProvider",
            "GeminiProvider",
            "GigaChatProvider",
            "OllamaProvider",
            "OpenAIProvider",
            "SaluteSpeechProvider",
            "YandexGPTProvider",
            "register_extended_providers",
        ],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(ai_providers, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in ai_providers.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 8 символов (4 western + 3 Russian + 1 helper)."""
        assert len(ai_providers.__all__) == 8

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает AI providers (S68 W4 decomp)."""
        assert ai_providers.__doc__ is not None
        assert "provider" in ai_providers.__doc__.lower() or "S68" in ai_providers.__doc__


@pytest.mark.unit
class TestAiProvidersFacadeIdentity:
    """Identity checks для 5 re-exports."""

    def test_claude_provider_is_class(self) -> None:
        """``ClaudeProvider`` — class (Anthropic provider)."""
        assert isinstance(ClaudeProvider, type)

    def test_gemini_provider_is_class(self) -> None:
        """``GeminiProvider`` — class (Google provider)."""
        assert isinstance(GeminiProvider, type)

    def test_ollama_provider_is_class(self) -> None:
        """``OllamaProvider`` — class (local provider)."""
        assert isinstance(OllamaProvider, type)

    def test_openai_provider_is_class(self) -> None:
        """``OpenAIProvider`` — class (OpenAI provider)."""
        assert isinstance(OpenAIProvider, type)

    def test_gigachat_provider_is_class(self) -> None:
        """``GigaChatProvider`` — class (Russian provider, FW4)."""
        assert isinstance(GigaChatProvider, type)

    def test_salute_speech_provider_is_class(self) -> None:
        """``SaluteSpeechProvider`` — class (Russian provider, FW4)."""
        assert isinstance(SaluteSpeechProvider, type)

    def test_yandex_gpt_provider_is_class(self) -> None:
        """``YandexGPTProvider`` — class (Russian provider, FW4)."""
        assert isinstance(YandexGPTProvider, type)

    def test_register_extended_providers_is_callable(self) -> None:
        """``register_extended_providers`` — callable (DI helper)."""
        assert callable(register_extended_providers)
