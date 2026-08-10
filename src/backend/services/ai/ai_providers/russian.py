"""Russian LLM providers (FW4).

YandexGPT, GigaChat, SaluteSpeech — все три российских провайдера
используют OpenAI-compatible API (litellm routing), что позволяет
реализовать их как тонкие обёртки поверх ``litellm.acompletion``.

Конфигурация через ``src.backend.core.config.ai``:
- ``yandexgpt_settings`` (``YANDEXGPT_*`` env / ``yandexgpt:`` YAML)
- ``gigachat_settings`` (``GIGACHAT_*`` env / ``gigachat:`` YAML)
- ``salute_speech_settings`` (``SALUTE_SPEECH_*`` env / ``salute_speech:`` YAML)

Все три реализуют ``BaseProvider``-like интерфейс (name + extract_text
+ chat + embeddings). Регистрация в AIGateway — через
``ai_providers/helpers.register_extended_providers()``.
"""
from __future__ import annotations

import asyncio
from typing import Any

from src.backend.core.config.ai import (
    gigachat_settings,
    salute_speech_settings,
    yandexgpt_settings,
)
from src.backend.core.logging import get_logger

__all__ = (
    "GigaChatProvider",
    "SaluteSpeechProvider",
    "YandexGPTProvider",
)

logger = get_logger("ai.providers.russian")


def _litellm_model(provider: str, model: str) -> str:
    """Добавляет ``<provider>/`` prefix если его нет (litellm routing)."""
    if "/" in model:
        return model
    return f"{provider}/{model}"


class _BaseRussianProvider:
    """Общая логика для OpenAI-compatible российских провайдеров."""

    name: str = ""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.api_key = api_key or self._default_api_key() or ""
        self.model = model or self._default_model()
        self.base_url = (
            base_url or self._default_base_url()
        ).rstrip("/")

    # Subclass hooks
    def _default_api_key(self) -> str:
        return ""

    def _default_model(self) -> str:
        return ""

    def _default_base_url(self) -> str:
        return ""

    def _provider_prefix(self) -> str:
        return "openai"  # litellm expects 'openai/' for OpenAI-compat APIs

    def extract_text(self, response: dict[str, Any]) -> str:
        """Извлечь text из OpenAI-format response (litellm)."""
        try:
            choices = response.get("choices", [])
            if choices:
                msg = choices[0].get("message", {})
                return msg.get("content", "") or ""
        except (AttributeError, IndexError, TypeError):
            pass
        return ""

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError(f"{self.name}: API key not set")
        import litellm

        prefixed_model = _litellm_model(self._provider_prefix(), model or self.model)
        return await litellm.acompletion(
            model=prefixed_model,
            messages=messages,
            api_key=self.api_key,
            api_base=self.base_url,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    async def embeddings(
        self,
        texts: list[str],
        *,
        model: str | None = None,
    ) -> list[list[float]]:
        if not self.api_key:
            raise RuntimeError(f"{self.name}: API key not set")
        import litellm

        prefixed_model = _litellm_model(
            self._provider_prefix(),
            model or "text-embedding-3-small",
        )
        response = await litellm.aembedding(
            model=prefixed_model,
            input=texts,
            api_key=self.api_key,
            api_base=self.base_url,
        )
        data = getattr(response, "data", None) or response.get("data", [])
        return [
            list(item["embedding"] if isinstance(item, dict) else item.embedding)
            for item in data
        ]


class YandexGPTProvider(_BaseRussianProvider):
    """YandexGPT через litellm (OpenAI-compatible API)."""

    name = "yandexgpt"

    def _default_api_key(self) -> str:
        return yandexgpt_settings.api_key

    def _default_model(self) -> str:
        return yandexgpt_settings.model

    def _default_base_url(self) -> str:
        return yandexgpt_settings.base_url

    def _provider_prefix(self) -> str:
        # YandexGPT: litellm routes as ``openai/`` (OpenAI-compat).
        return "openai"


class GigaChatProvider(_BaseRussianProvider):
    """GigaChat через litellm.

    Note: GigaChat API — НЕ OpenAI-compatible. Требует OAuth2 access_token
    (scope GIGACHAT_API_PERS / _CORP). litellm имеет экспериментальную
    поддержку через ``gigachat/`` prefix, но в production чаще
    используется прямой HTTP client. Skeleton оставлен для
    совместимости с AIGateway Provider-интерфейсом.
    """

    name = "gigachat"

    def _default_api_key(self) -> str:
        return gigachat_settings.credentials  # OAuth2 creds

    def _default_model(self) -> str:
        return gigachat_settings.model

    def _default_base_url(self) -> str:
        return gigachat_settings.base_url

    def _provider_prefix(self) -> str:
        return "gigachat"


class SaluteSpeechProvider(_BaseRussianProvider):
    """SaluteSpeech через litellm (OpenAI-compatible)."""

    name = "salute_speech"

    def _default_api_key(self) -> str:
        return salute_speech_settings.credentials  # OAuth2 creds

    def _default_model(self) -> str:
        return salute_speech_settings.model

    def _default_base_url(self) -> str:
        return salute_speech_settings.base_url

    def _provider_prefix(self) -> str:
        return "openai"  # OpenAI-compatible API


# При импорте модуля — ленивая регистрация (если есть AIGateway).
async def _smoke_test_providers() -> None:
    """Smoke-test: инстанцировать 3 провайдера, проверить name + model.

    Вызывается вручную (не auto-run при import — лишний overhead).
    """
    for cls in (YandexGPTProvider, GigaChatProvider, SaluteSpeechProvider):
        try:
            p = cls()  # без API key — smoke
            assert p.name == cls.name
            assert p.model, f"{cls.name}: empty model"
            logger.info("russian_provider_smoke_ok", extra={"provider": p.name})
        except Exception as exc:
            logger.warning(
                "russian_provider_smoke_failed",
                extra={"provider": cls.name, "error": str(exc)},
            )


if __name__ == "__main__":
    asyncio.run(_smoke_test_providers())
