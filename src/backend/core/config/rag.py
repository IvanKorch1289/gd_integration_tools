"""Настройки RAG (Retrieval-Augmented Generation)."""

from typing import ClassVar

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.config_loader import BaseSettingsWithLoader

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
            "openai. Legacy: fastembed (только Python ≤ 3.13, через "
            "extra embeddings-fastembed-legacy)."
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

    # --- Block 3.5 (gap-ai-3.5, ADR-0074): embedding provenance --------
    embedding_strict_mode: bool = Field(
        default=False,
        description=(
            "Block 3.5: retrieval фильтрует chunks с "
            "metadata.embedding_model != current rag.embedding_model. "
            "Counter rag_model_mismatch_total{chunk_model, current_model} "
            "инкрементируется в обоих режимах. Default-OFF — оставить "
            "warn-only до полного re-embed, ON — после migration."
        ),
    )

    # --- Block 3.2 (gap-ai-3.2): hybrid retrieval ---------------------
    hybrid_enabled: bool = Field(
        default=False,
        description=(
            "Block 3.2: hybrid retriever (dense + BM25 + RRF) поверх "
            "vector store. При True RAGService.search комбинирует семантику "
            "Qdrant с lexical BM25 через Reciprocal Rank Fusion (k=60 default)."
        ),
    )
    rrf_k: int = Field(
        default=60,
        ge=1,
        description="Block 3.2: Reciprocal Rank Fusion параметр k (default 60).",
    )

    # --- Block 3.3 (gap-ai-3.3): source attribution -------------------
    source_attribution_enabled: bool = Field(
        default=True,
        description=(
            "Block 3.3: добавлять source_id/filename в augmented prompt + "
            "возвращать source_attribution: list[str] в response. "
            "Default-ON — без compliance-impact."
        ),
    )


rag_settings = RAGSettings()
