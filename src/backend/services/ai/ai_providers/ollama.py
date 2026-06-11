from __future__ import annotations

"""S68 W4 - ollama.py part of ai_providers decomp.

Ollama local provider (extract_text, embeddings, chat).

Classes: OllamaProvider.
"""

import os
from typing import Any

import httpx

from src.backend.core.net import OutboundHttpClient


class OllamaProvider:
    """Ollama local model provider.

    Requires: Ollama server running (default http://localhost:11434).
    Models: любая модель через `ollama pull {model}`.
    Benefits: no API costs, full privacy, offline capable.
    """

    name = "ollama"

    def __init__(self, *, base_url: str | None = None, model: str = "llama3.2") -> None:
        self.base_url = base_url or os.environ.get(
            "OLLAMA_URL", "http://localhost:11434"
        )
        self.model = model

    def extract_text(self, response: dict[str, Any]) -> str:
        """Извлекает текст из Ollama (``message.content``)."""
        try:
            return response.get("message", {}).get("content", "") or response.get(
                "response", ""
            )
        except AttributeError, TypeError:
            return ""

    async def embeddings(
        self, texts: list[str], *, model: str | None = None
    ) -> list[list[float]]:
        """Embeddings через Ollama /api/embeddings (по одному запросу на текст)."""
        out: list[list[float]] = []
        async with OutboundHttpClient(timeout=httpx.Timeout(60)) as client:
            for text in texts:
                resp = await client.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": model or self.model, "prompt": text},
                )
                resp.raise_for_status()
                data = resp.json()
                out.append(data.get("embedding", []))
        return out

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
        """Chat completion через Ollama API."""
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "options": {"num_predict": max_tokens, "temperature": temperature},
            "stream": stream,
        }
        if tools:
            payload["tools"] = tools

        async with OutboundHttpClient(timeout=httpx.Timeout(120)) as client:
            resp = await client.post(f"{self.base_url}/api/chat", json=payload)
            resp.raise_for_status()
            return resp.json()
