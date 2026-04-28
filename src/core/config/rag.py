"""Настройки RAG (Retrieval-Augmented Generation)."""

from typing import ClassVar

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.core.config.config_loader import BaseSettingsWithLoader

__all__ = ("RAGSettings", "rag_settings")


class RAGSettings(BaseSettingsWithLoader):
    """Конфигурация RAG pipeline.

    `vector_backend` определяет хранилище эмбеддингов (qdrant / chroma / faiss).
    `embedding_provider` отвязывает RAGService от конкретной библиотеки —
    поддерживаются sentence-transformers (default), ollama и openai-compatible
    HTTP-эндпоинты, опциональный fastembed (ONNX). На Python 3.14 fastembed
    нестабилен в рантайме, поэтому default — sentence-transformers.
    """

    yaml_group: ClassVar[str] = "rag"
    model_config = SettingsConfigDict(env_prefix="RAG_", extra="forbid")

    # --- Vector store --------------------------------------------------
    vector_backend: str = Field(
        "qdrant", description="Vector store backend: qdrant, chroma, faiss."
    )
    # Qdrant
    qdrant_url: str = Field(
        "http://localhost:6333", description="HTTP URL Qdrant-сервера."
    )
    qdrant_collection: str = Field(
        "gd_rag", description="Коллекция Qdrant по умолчанию."
    )
    qdrant_api_key: str | None = Field(
        None, description="API-ключ Qdrant Cloud (опционально)."
    )
    # Chroma (fallback / legacy)
    chroma_host: str = Field("localhost", description="Хост Chroma DB.")
    chroma_port: int = Field(8000, gt=0, lt=65536, description="Порт Chroma DB.")
    chroma_collection: str = Field("gd_rag", description="Коллекция Chroma.")

    # --- Embeddings ----------------------------------------------------
    embedding_provider: str = Field(
        "sentence-transformers",
        description=(
            "Провайдер эмбеддингов: sentence-transformers (default), ollama, "
            "openai, fastembed."
        ),
    )
    embedding_model: str = Field(
        "all-MiniLM-L6-v2",
        description="Название модели эмбеддингов в выбранном провайдере.",
    )
    embedding_endpoint: str | None = Field(
        None,
        description=(
            "URL HTTP-эндпоинта для ollama/openai провайдеров. "
            "Для sentence-transformers и fastembed не используется."
        ),
    )
    embedding_api_key: str | None = Field(
        None, description="API-ключ для openai-совместимого endpoint."
    )

    # --- Pipeline ------------------------------------------------------
    chunk_size: int = Field(512, ge=64, description="Размер чанка (символов).")
    chunk_overlap: int = Field(50, ge=0, description="Перекрытие чанков.")
    top_k: int = Field(5, ge=1, le=100, description="Кол-во результатов поиска.")
    enabled: bool = Field(False, description="Включить RAG.")


rag_settings = RAGSettings()
