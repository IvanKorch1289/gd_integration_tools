"""AI Providers — Claude (Anthropic), Gemini (Google), Ollama (local).

Расширяет ai_agent.py fallback chain с 3 новыми провайдерами.
Все SDK lazy-imported; при отсутствии провайдер недоступен.

Кеширование на диске (через существующий core.decorators.caching)
добавляется на уровне ai_agent.chat() (fallback при недоступности Redis).

Multi-instance safety:
- Stateless HTTP calls
- API keys из settings (single source)
- Кеш Redis-first (shared) + disk-fallback (per-instance)
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

__all__ = (
    "ClaudeProvider",
    "GeminiProvider",
    "OllamaProvider",
)

logger = logging.getLogger("services.ai_providers")


class ClaudeProvider:
    """Anthropic Claude provider.

    Requires: ANTHROPIC_API_KEY env.
    Models: claude-3-5-sonnet / claude-3-opus / claude-3-haiku.

    Supports: function calling (tools), streaming, multi-modal (images).
    """

    def __init__(self, *, api_key: str | None = None, model: str = "claude-3-5-sonnet-20241022") -> None:
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model
        self.base_url = "https://api.anthropic.com/v1"

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

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self.base_url}/messages",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()


class GeminiProvider:
    """Google Gemini provider.

    Requires: GEMINI_API_KEY env.
    Models: gemini-1.5-pro / gemini-1.5-flash.
    Supports: multi-modal (images), function calling.
    """

    def __init__(self, *, api_key: str | None = None, model: str = "gemini-1.5-pro") -> None:
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.model = model
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"

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
            contents.append({
                "role": role,
                "parts": [{"text": msg.get("content", "")}],
            })

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

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()


class OllamaProvider:
    """Ollama local model provider.

    Requires: Ollama server running (default http://localhost:11434).
    Models: любая модель через `ollama pull {model}`.
    Benefits: no API costs, full privacy, offline capable.
    """

    def __init__(self, *, base_url: str | None = None, model: str = "llama3.2") -> None:
        self.base_url = base_url or os.environ.get("OLLAMA_URL", "http://localhost:11434")
        self.model = model

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
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
            "stream": stream,
        }
        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self.base_url}/api/chat",
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()


def register_extended_providers(agent: Any) -> int:
    """Регистрирует Claude/Gemini/Ollama в ai_agent._providers.

    Вызвать при startup после get_ai_agent_service().
    Возвращает количество успешно зарегистрированных провайдеров.
    """
    registered = 0

    if os.environ.get("ANTHROPIC_API_KEY"):
        claude = ClaudeProvider()
        agent._providers["anthropic"] = claude.chat
        agent._providers["claude"] = claude.chat
        registered += 1

    if os.environ.get("GEMINI_API_KEY"):
        gemini = GeminiProvider()
        agent._providers["gemini"] = gemini.chat
        agent._providers["google"] = gemini.chat
        registered += 1

    if os.environ.get("OLLAMA_URL") or os.environ.get("OLLAMA_ENABLED", "").lower() == "true":
        ollama = OllamaProvider()
        agent._providers["ollama"] = ollama.chat
        agent._providers["local"] = ollama.chat
        registered += 1

    logger.info("Registered %d extended AI providers", registered)
    return registered
