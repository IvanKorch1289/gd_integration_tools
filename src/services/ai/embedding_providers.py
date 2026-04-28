"""Провайдеры эмбеддингов для RAGService.

Назначение — отвязать RAGService от конкретной библиотеки эмбеддингов
и дать единый async API. Поддерживаются:

* ``sentence-transformers`` — default (PyTorch, локальная модель).
* ``ollama`` — HTTP к Ollama-серверу (через ``OllamaProvider.embeddings``).
* ``openai`` — HTTP к OpenAI-compatible эндпоинту
  (через ``OpenAIProvider.embeddings``).
* ``fastembed`` — opt-in (ONNX), на Python 3.14 рантайм нестабилен;
  используется только если явно выбран в ``rag_settings``.

Все провайдеры реализуют ``EmbeddingProvider`` Protocol с одним методом
``embed(texts) -> list[list[float]]``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol, runtime_checkable

__all__ = (
    "EmbeddingProvider",
    "FastembedEmbeddingProvider",
    "OllamaEmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "SentenceTransformerEmbeddingProvider",
    "get_embedding_provider",
)

logger = logging.getLogger(__name__)


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Async provider эмбеддингов."""

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class SentenceTransformerEmbeddingProvider:
    """Локальные эмбеддинги через ``sentence-transformers`` (PyTorch).

    Default-провайдер RAG: работает offline, не требует внешних сервисов,
    стабильно собирается на Python 3.14 (PyTorch имеет колёса для 3.14).
    Модель загружается лениво при первом вызове ``embed``.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self._model_name = model_name
        self._model: Any = None

    def _ensure_model(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers не установлен — добавьте extras [rag]: "
                "pip install '.[rag]'"
            ) from exc
        self._model = SentenceTransformer(self._model_name)
        logger.info("SentenceTransformer model %r loaded", self._model_name)
        return self._model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        def _encode() -> list[list[float]]:
            model = self._ensure_model()
            vectors = model.encode(texts, convert_to_numpy=True)
            return [v.tolist() for v in vectors]

        return await asyncio.to_thread(_encode)


class FastembedEmbeddingProvider:
    """ONNX-эмбеддинги через ``fastembed`` (opt-in).

    Внимание: на Python 3.14 рантайм fastembed нестабилен (загрузка
    ONNX-моделей зависает); используйте только если выбран явно.
    """

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5") -> None:
        self._model_name = model_name
        self._model: Any = None

    def _ensure_model(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise RuntimeError(
                "fastembed не установлен — установите fastembed или выберите "
                "другой embedding_provider в rag_settings"
            ) from exc
        self._model = TextEmbedding(model_name=self._model_name)
        return self._model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        def _encode() -> list[list[float]]:
            model = self._ensure_model()
            return [vec.tolist() for vec in model.embed(texts)]

        return await asyncio.to_thread(_encode)


class OllamaEmbeddingProvider:
    """Эмбеддинги через Ollama HTTP API."""

    def __init__(
        self, model_name: str = "nomic-embed-text", base_url: str | None = None
    ) -> None:
        self._model_name = model_name
        self._base_url = base_url
        self._provider: Any = None

    def _ensure_provider(self) -> Any:
        if self._provider is not None:
            return self._provider
        from src.services.ai.ai_providers import OllamaProvider

        self._provider = OllamaProvider(base_url=self._base_url, model=self._model_name)
        return self._provider

    async def embed(self, texts: list[str]) -> list[list[float]]:
        provider = self._ensure_provider()
        return await provider.embeddings(texts, model=self._model_name)


class OpenAIEmbeddingProvider:
    """Эмбеддинги через OpenAI / openai-compatible endpoint."""

    def __init__(
        self,
        model_name: str = "text-embedding-3-small",
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self._model_name = model_name
        self._base_url = base_url
        self._api_key = api_key
        self._provider: Any = None

    def _ensure_provider(self) -> Any:
        if self._provider is not None:
            return self._provider
        from src.services.ai.ai_providers import OpenAIProvider

        self._provider = OpenAIProvider(
            api_key=self._api_key, model=self._model_name, base_url=self._base_url
        )
        return self._provider

    async def embed(self, texts: list[str]) -> list[list[float]]:
        provider = self._ensure_provider()
        return await provider.embeddings(texts, model=self._model_name)


def get_embedding_provider() -> EmbeddingProvider:
    """Собирает провайдер по ``rag_settings.embedding_provider``."""
    from src.core.config.rag import rag_settings

    provider_name = (rag_settings.embedding_provider or "sentence-transformers").lower()
    model = rag_settings.embedding_model

    match provider_name:
        case "sentence-transformers" | "st":
            return SentenceTransformerEmbeddingProvider(model_name=model)
        case "fastembed":
            return FastembedEmbeddingProvider(model_name=model)
        case "ollama":
            return OllamaEmbeddingProvider(
                model_name=model, base_url=rag_settings.embedding_endpoint
            )
        case "openai":
            return OpenAIEmbeddingProvider(
                model_name=model,
                base_url=rag_settings.embedding_endpoint,
                api_key=rag_settings.embedding_api_key,
            )
        case _:
            raise ValueError(
                f"Неизвестный embedding_provider: {provider_name!r}. "
                "Поддерживается: sentence-transformers, ollama, openai, fastembed."
            )
