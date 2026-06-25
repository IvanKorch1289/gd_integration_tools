"""Sprint 170 M3 — MiniMax provider (OpenAI-compatible).

MiniMax M-series (minimax-m2, minimax-m2.5, MiniMax-Text-01). OpenAI-compatible API.
Endpoint: https://api.minimax.chat/v1

Uses OutboundHttpClient через WAF + capability gate.
"""
from __future__ import annotations

import os
from typing import Any

from src.backend.services.ai.ai_providers.openai import OpenAIProvider


class MiniMaxProvider:
    """MiniMax M-series — OpenAI-compatible Chinese LLM.

    Ponytail: наследует OpenAIProvider, переопределяет только defaults.
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
            "MINIMAX_BASE_URL", "https://api.minimax.chat/v1"
        )
        self._delegate = OpenAIProvider(
            api_key=self.api_key, model=self.model, base_url=self.base_url
        )

    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        """Chat completion через MiniMax API."""
        return await self._delegate.chat(messages, **kwargs)

    async def embeddings(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        """Embeddings через MiniMax API."""
        return await self._delegate.embeddings(texts, **kwargs)

    async def extract_text(self, content: bytes, **kwargs: Any) -> str:
        """Extract text (delegates to OpenAI)."""
        return await self._delegate.extract_text(content, **kwargs)
