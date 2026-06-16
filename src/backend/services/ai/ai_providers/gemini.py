"""S68 W4 - gemini.py part of ai_providers decomp.

Google Gemini provider (extract_text, embeddings, chat).

Classes: GeminiProvider.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from src.backend.core.net import OutboundHttpClient


class GeminiProvider:
    """Google Gemini provider.

    Requires: GEMINI_API_KEY env.
    Models: gemini-1.5-pro / gemini-1.5-flash.
    Supports: multi-modal (images), function calling.
    """

    name = "gemini"

    def __init__(
        self, *, api_key: str | None = None, model: str = "gemini-1.5-pro"
    ) -> None:
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.model = model
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"

    def extract_text(self, response: dict[str, Any]) -> str:
        """Извлекает текст из Gemini (``candidates[0].content.parts[0].text``)."""
        try:
            cands = response.get("candidates", [])
            if cands:
                parts = cands[0].get("content", {}).get("parts", [])
                if parts:
                    return parts[0].get("text", "")
        except AttributeError, IndexError, TypeError:
            pass
        return ""

    async def embeddings(
        self, texts: list[str], *, model: str | None = None
    ) -> list[list[float]]:
        """Возвращает embeddings батча текстов через Gemini embedContent.

        Использует endpoint ``/v1beta/models/{model}:embedContent``
        с ``taskType=RETRIEVAL_DOCUMENT``. Для каждого текста выполняется
        отдельный HTTP-запрос (Gemini не поддерживает batch-вход
        в embedContent). Requires ``GEMINI_API_KEY``.

        Args:
            texts: Список входных текстов.
            model: Имя embedding-модели (например ``text-embedding-004``).
                По умолчанию ``text-embedding-004``.

        Returns:
            Список векторов (каждый — ``list[float]``) в порядке входа.

        Raises:
            RuntimeError: Если ``GEMINI_API_KEY`` не задан или
                ответ Gemini не содержит поле ``embedding.values``.
        """
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY not set")

        embed_model = model or "text-embedding-004"
        url = f"{self.base_url}/models/{embed_model}:embedContent"
        headers = {"Content-Type": "application/json"}
        params = {"key": self.api_key}

        vectors: list[list[float]] = []
        async with OutboundHttpClient(timeout=httpx.Timeout(30.0)) as client:
            for text in texts:
                payload = {
                    "model": f"models/{embed_model}",
                    "content": {"parts": [{"text": text}]},
                    "taskType": "RETRIEVAL_DOCUMENT",
                }
                response = await client.post(
                    url, headers=headers, params=params, json=payload
                )
                response.raise_for_status()
                data = response.json()
                values = data.get("embedding", {}).get("values") or data.get(
                    "embeddings", [{}]
                )[0].get("values")
                if not values:
                    raise RuntimeError(
                        f"Gemini embeddings: empty response for model={embed_model}"
                    )
                vectors.append([float(v) for v in values])
        return vectors

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
        """Chat completion через Gemini API."""
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY not set")

        # Gemini: role=user/model, no 'system'
        contents = []
        for msg in messages:
            role = "user" if msg.get("role") == "user" else "model"
            contents.append({"role": role, "parts": [{"text": msg.get("content", "")}]})

        payload = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            },
        }
        if tools:
            payload["tools"] = tools

        model_name = model or self.model
        endpoint = "streamGenerateContent" if stream else "generateContent"
        url = f"{self.base_url}/models/{model_name}:{endpoint}?key={self.api_key}"

        async with OutboundHttpClient(timeout=httpx.Timeout(60)) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()
