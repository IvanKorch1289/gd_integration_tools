"""MiniMax provider via litellm (B1_LITELLM).

MiniMax M-series — OpenAI-compatible. Делегирует к OpenAIProvider,
который использует ``litellm.acompletion`` / ``aembedding``
с ``api_base`` = MiniMax endpoint.
"""
from __future__ import annotations

import os
from typing import Any

from src.backend.services.ai.ai_providers.openai import OpenAIProvider


class MiniMaxProvider:
    """MiniMax M-series — OpenAI-compatible Chinese LLM.

    Ponytail: наследует OpenAIProvider (litellm), переопределяет только defaults.
    """

    name = "minimax"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "MiniMax-Text-01",
        base_url: str | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("MINIMAX_API_KEY", "")
        self.model = model
        self.base_url = base_url or os.environ.get(
            "MINIMAX_BASE_URL", "https://api.minimax.chat/v1",
        )
        self._delegate = OpenAIProvider(
            api_key=self.api_key, model=self.model, base_url=self.base_url,
        )

    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        """Chat completion через MiniMax API (litellm)."""
        return await self._delegate.chat(messages, **kwargs)

    async def embeddings(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        """Embeddings через MiniMax API (litellm)."""
        if not self.api_key:
            raise RuntimeError("MINIMAX_API_KEY not set")
        return await self._delegate.embeddings(texts, **kwargs)

    def extract_text(self, response: dict[str, Any]) -> str:
        """litellm нормализует ответ к OpenAI-формату."""
        return self._delegate.extract_text(response)
