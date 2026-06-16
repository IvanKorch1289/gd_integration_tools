"""S68 W4 - openai.py part of ai_providers decomp.

OpenAI provider (extract_text, embeddings, chat).

Classes: OpenAIProvider.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from src.backend.core.net import OutboundHttpClient


class OpenAIProvider:
    """OpenAI GPT-провайдер.

    Requires: OPENAI_API_KEY env (+ опционально OPENAI_BASE_URL для azure/
    openai-compatible прокси вроде LiteLLM / vLLM).
    Models: gpt-4o / gpt-4o-mini / gpt-4-turbo.

    Поддержка tool-calling и streaming идентична OpenAI-API, так что провайдер
    работает с любым openai-compatible backend'ом (LocalAI, vLLM, LiteLLM,
    OpenRouter, Ollama openai-endpoint).
    """

    name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
        base_url: str | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.model = model
        self.base_url = (
            base_url or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"
        ).rstrip("/")

    def extract_text(self, response: dict[str, Any]) -> str:
        """OpenAI-format: ``choices[0].message.content``."""
        try:
            choices = response.get("choices", [])
            if choices:
                msg = choices[0].get("message", {})
                return msg.get("content", "") or ""
        except AttributeError, IndexError, TypeError:
            pass
        return ""

    async def embeddings(
        self, texts: list[str], *, model: str | None = None
    ) -> list[list[float]]:
        """Embeddings через ``/embeddings`` endpoint (batch-запрос)."""
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY not set")
        payload = {"model": model or "text-embedding-3-small", "input": texts}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with OutboundHttpClient(timeout=httpx.Timeout(60)) as client:
            resp = await client.post(
                f"{self.base_url}/embeddings", headers=headers, json=payload
            )
            resp.raise_for_status()
            data = resp.json()
            return [item["embedding"] for item in data.get("data", [])]

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
        """Chat completion через OpenAI / openai-compatible API."""
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY not set")

        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": stream,
        }
        if tools:
            payload["tools"] = tools

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with OutboundHttpClient(timeout=httpx.Timeout(60)) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions", headers=headers, json=payload
            )
            resp.raise_for_status()
            return resp.json()
