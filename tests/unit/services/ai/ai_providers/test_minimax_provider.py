"""Tests for MiniMaxProvider (Sprint 170 M3).

Covers:
- Default settings (model, base_url, api_key fallback)
- Env var override
- Delegation to OpenAIProvider
- Key isolation (raises if MINIMAX_API_KEY unset)
"""
from __future__ import annotations
import os
from unittest.mock import AsyncMock, patch

import pytest


class TestMiniMaxProviderDefaults:
    def test_default_model(self) -> None:
        from src.backend.services.ai.ai_providers.minimax import MiniMaxProvider
        p = MiniMaxProvider(api_key="test-key")
        assert p.model == "MiniMax-Text-01"
        assert p.base_url == "https://api.minimax.chat/v1"
        assert p.api_key == "test-key"

    def test_env_var_override(self) -> None:
        from src.backend.services.ai.ai_providers.minimax import MiniMaxProvider
        with patch.dict(os.environ, {"MINIMAX_API_KEY": "env-key", "MINIMAX_BASE_URL": "https://custom.api/v1"}):
            p = MiniMaxProvider()
            assert p.api_key == "env-key"
            assert p.base_url == "https://custom.api/v1"


class TestMiniMaxProviderDelegation:
    @pytest.mark.asyncio
    async def test_chat_delegates_to_openai(self) -> None:
        from src.backend.services.ai.ai_providers.minimax import MiniMaxProvider
        p = MiniMaxProvider(api_key="test-key")
        p._delegate.chat = AsyncMock(return_value={"choices": [{"message": {"content": "ok"}}]})
        result = await p.chat([{"role": "user", "content": "hi"}])
        p._delegate.chat.assert_called_once()
        assert result == {"choices": [{"message": {"content": "ok"}}]}

    @pytest.mark.asyncio
    async def test_embeddings_key_isolation(self) -> None:
        from src.backend.services.ai.ai_providers.minimax import MiniMaxProvider
        # Patch the resolved api_key post-init to simulate missing key
        p = MiniMaxProvider(api_key="test-key")
        p.api_key = ""  # simulate no key after resolution
        with pytest.raises(RuntimeError, match="MINIMAX_API_KEY"):
            await p.embeddings(["text"])

    @pytest.mark.asyncio
    async def test_embeddings_delegates(self) -> None:
        from src.backend.services.ai.ai_providers.minimax import MiniMaxProvider
        p = MiniMaxProvider(api_key="test-key")
        p._delegate.embeddings = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
        result = await p.embeddings(["text"])
        p._delegate.embeddings.assert_called_once()
        assert result == [[0.1, 0.2, 0.3]]
