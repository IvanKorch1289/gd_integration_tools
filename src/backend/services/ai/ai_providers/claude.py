"""S68 W4 - claude.py part of ai_providers decomp.

Anthropic Claude provider (extract_text, embeddings, chat).

Classes: ClaudeProvider.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from src.backend.core.net import OutboundHttpClient


class ClaudeProvider:
    """Anthropic Claude provider.

    Requires: ANTHROPIC_API_KEY env.
    Models: claude-3-5-sonnet / claude-3-opus / claude-3-haiku.

    Supports: function calling (tools), streaming, multi-modal (images).
    """

    name = "claude"

    def __init__(
        self, *, api_key: str | None = None, model: str = "claude-3-5-sonnet-20241022"
    ) -> None:
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model
        self.base_url = "https://api.anthropic.com/v1"

    def extract_text(self, response: dict[str, Any]) -> str:
        """Извлекает текст из ответа Anthropic (``content[0].text``)."""
        try:
            blocks = response.get("content", [])
            if blocks and isinstance(blocks, list):
                return blocks[0].get("text", "")
        except (AttributeError, IndexError, TypeError):
            pass
        return ""

    async def embeddings(
        self, texts: list[str], *, model: str | None = None
    ) -> list[list[float]]:
        """Anthropic не предоставляет embeddings API — используйте Voyage/OpenAI."""
        raise NotImplementedError("Claude API не поддерживает embeddings")

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: list[dict] | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        """Chat completion через Claude API."""
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")

        # Claude API: system message отдельно от messages
        system_msg = ""
        user_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                system_msg = msg.get("content", "")
            else:
                user_messages.append(msg)

        payload: dict[str, Any] = {
            "model": model or self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": user_messages,
        }
        if system_msg:
            payload["system"] = system_msg
        if tools:
            payload["tools"] = tools
        if stream:
            payload["stream"] = True

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        async with OutboundHttpClient(timeout=httpx.Timeout(60)) as client:
            resp = await client.post(
                f"{self.base_url}/messages", headers=headers, json=payload
            )
            resp.raise_for_status()
            return resp.json()
