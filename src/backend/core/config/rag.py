"""Настройки RAG (Retrieval-Augmented Generation)."""

from typing import ClassVar

from pydantic import BaseModel, Field
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.config_loader import BaseSettingsWithLoader

__all__ = (
    "RAGSettings",
    "rag_settings",
    "HyDESettings",
    "MultiQuerySettings",
    "HybridSettings",
    "StrategyThresholdsSettings",
    "AdaptiveRAGSettings",
)


class HyDESettings(BaseModel):
    """Параметры HyDE (Hypothetical Document Embedding) стратегии."""

    max_tokens: int = Field(
        256, ge=1, description="Макс. токенов для hypothetical answer."
    )
    temperature: float = Field(
        0.1, ge=0.0, le=2.0, description="Температура генерации HyDE."
    )
    prompt_template: str = Field(
        "Напиши краткий идеальный ответ на следующий вопрос. Отвечай только по существу, без введения. Вопрос: {query}",
        description="Шаблон промпта для HyDE.",
    )
    include_hypothetical_in_result: bool = Field(
        False, description="Включать hypothetical answer в итоговый результат."
    )


class MultiQuerySettings(BaseModel):
    """Параметры Multi-query стратегии."""

    num_reformulations: int = Field(
        5, ge=1, description="Число реформулировок запроса."
    )
    rrf_k: int = Field(60, ge=1, description="RRF параметр k для multi-query.")
    parallel: bool = Field(True, description="Запускать реформулировки параллельно.")
    prompt_template: str = Field(
        "Переформулируй следующий запрос {n} различными способами. Каждая реформализация должна раскрывать разный аспект или использовать синонимы. Верни только список реформализаций, по одной на строке. Оригинальный запрос: {query}",
        description="Шаблон промпта для multi-query.",
    )


class HybridSettings(BaseModel):
    """Параметры Hybrid (dense + sparse) стратегии."""

    rrf_k: int = Field(60, ge=1, description="RRF параметр k для hybrid.")


class StrategyThresholdsSettings(BaseModel):
    """Пороги переключения adaptive-стратегий."""

    min_confidence_for_llm: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Минимальная уверенность для вызова LLM-классификатора.",
    )
    cache_size: int = Field(512, ge=1, description="Размер кэша стратегий.")


class AdaptiveRAGSettings(BaseModel):
    """Adaptive RAG стратегии (Sprint 19 K4)."""

    enabled: bool = Field(True, description="Включить adaptive RAG.")
    default_strategy: str = Field(
        "dense", description="Стратегия по умолчанию (dense/hybrid/hyde/multi_query)."
    )
    hyde: HyDESettings = Field(default_factory=HyDESettings)
    multi_query: MultiQuerySettings = Field(default_factory=MultiQuerySettings)
    hybrid: HybridSettings = Field(default_factory=HybridSettings)
    strategy_thresholds: StrategyThresholdsSettings = Field(
        default_factory=StrategyThresholdsSettings
    )


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

    # --- Adaptive RAG (base.yml) ---------------------------------------
    adaptive: AdaptiveRAGSettings = Field(default_factory=AdaptiveRAGSettings)

    # --- Block 3.5 (gap-ai-3.5, ADR-0074): embedding provenance --------
    embedding_strict_mode: bool = Field(
        default=True,
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
        default=True,
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
