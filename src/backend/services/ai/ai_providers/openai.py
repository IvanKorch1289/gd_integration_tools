"""OpenAI provider via litellm (B1_LITELLM).

litellm нормализует вызов и ответ к OpenAI-формату для любого совместимого
backend'а (OpenAI, vLLM, LocalAI, OpenRouter, MiniMax, и т.д.).
"""

from __future__ import annotations

from typing import Any

from src.backend.core.config.ai import openai_settings


def _litellm_model(model: str) -> str:
    """Добавляет ``openai/`` prefix если его нет — для litellm routing."""
    return model if "/" in model else f"openai/{model}"


class OpenAIProvider:
    """OpenAI GPT-провайдер через ``litellm.acompletion`` / ``aembedding``.

    Requires: OPENAI_API_KEY env (+ опционально OPENAI_BASE_URL для azure/
    openai-compatible прокси вроде LiteLLM / vLLM).
    """

    name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
        base_url: str | None = None,
    ) -> None:
        self.api_key = api_key or openai_settings.api_key
        self.model = model
        self.base_url = (
            base_url or openai_settings.base_url
        ).rstrip("/")

    def extract_text(self, response: dict[str, Any]) -> str:
        """Litellm нормализует все ответы к OpenAI-формату."""
        try:
            choices = response.get("choices", [])
            if choices:
                msg = choices[0].get("message", {})
                return msg.get("content", "") or ""
        except (AttributeError, IndexError, TypeError):  # noqa: violation-check — narrow API-shape fallback
            pass
        return ""

    async def embeddings(
        self, texts: list[str], *, model: str | None = None,
    ) -> list[list[float]]:
        """Embeddings через ``litellm.aembedding``."""
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY not set")
        import litellm

        response = await litellm.aembedding(
            model=_litellm_model(model or "text-embedding-3-small"),
            input=texts,
            api_key=self.api_key,
            api_base=self.base_url,
        )
        data = getattr(response, "data", None) or response.get("data", [])
        return [
            list(item["embedding"] if isinstance(item, dict) else item.embedding)
            for item in data
        ]

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
        """Chat completion через ``litellm.acompletion``."""
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY not set")
        import litellm

        kwargs: dict[str, Any] = {
            "model": _litellm_model(model or self.model),
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": stream,
            "api_key": self.api_key,
            "api_base": self.base_url,
        }
        if tools:
            kwargs["tools"] = tools
        response = await litellm.acompletion(**kwargs)
        return response.model_dump() if hasattr(response, "model_dump") else dict(response)
