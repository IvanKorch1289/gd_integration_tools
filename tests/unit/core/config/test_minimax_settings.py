"""Tests for MiniMaxSettings (Sprint 170 M3 dir 1)."""
from __future__ import annotations

import pytest


class TestMiniMaxSettingsDefaults:
    def test_default_model(self) -> None:
        from src.backend.core.config.ai import minimax_settings
        assert minimax_settings.model == "MiniMax-Text-01"

    def test_default_base_url(self) -> None:
        from src.backend.core.config.ai import minimax_settings
        assert minimax_settings.base_url == "https://api.minimax.chat/v1"

    def test_default_timeout(self) -> None:
        from src.backend.core.config.ai import minimax_settings
        assert minimax_settings.timeout == 30.0

    def test_default_max_retries(self) -> None:
        from src.backend.core.config.ai import minimax_settings
        assert minimax_settings.max_retries == 3

    def test_yaml_group(self) -> None:
        from src.backend.core.config.ai import MiniMaxSettings
        assert MiniMaxSettings.yaml_group == "minimax"


class TestFallbackChainIncludesMiniMax:
    def test_minimax_in_fallback_chain(self) -> None:
        from src.backend.core.config.ai import ai_providers_settings
        assert "minimax" in ai_providers_settings.fallback_chain
