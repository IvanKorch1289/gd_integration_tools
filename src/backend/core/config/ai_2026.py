"""Настройки AI Stack 2026 (К4 MVP).

Каркас новых блоков для Sprint 1/3/4/5/7:

* :class:`LiteLLMGatewaySettings` — единый шлюз LLM-провайдеров
  (litellm.acompletion / aembedding) с native streaming и cost callback;
* :class:`RagCacheSettings` — 3-tier RAG cache (L1 KV / L2 semantic / L3 retrieval);
* :class:`BGESettings` — BGE-M3 embedding-модель + reranker-v2-m3;
* :class:`LangMemSettings` — long-term memory (episodic / semantic / procedural);
* :class:`StreamingLLMSettings` — token-level стриминг через SSE / WS / Webhook.

Все блоки — default-OFF (`*_enabled=False`) кроме L1 и L3 cache, как и
оговорено в плане MVP. Резолв ad-hoc через `XxxSettings()` (как
`PerplexitySettings` в `services/ai/ai_agent.py`) — без правки
`core/config/settings.py`.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.config_loader import BaseSettingsWithLoader

__all__ = (
    "LiteLLMGatewaySettings",
    "RagCacheSettings",
    "RagIngestSettings",
    "BGESettings",
    "LangMemSettings",
    "StreamingLLMSettings",
    "LangFuseSettings",
    "McpSettings",
    "litellm_gateway_settings",
    "rag_cache_settings",
    "rag_ingest_settings",
    "bge_settings",
    "langmem_settings",
    "streaming_llm_settings",
    "langfuse_settings",
    "mcp_settings",
)


class LiteLLMGatewaySettings(BaseSettingsWithLoader):
    """Параметры LiteLLM-шлюза (acompletion / aembedding / cost-callback)."""

    yaml_group: ClassVar[str] = "litellm_gateway"
    model_config = SettingsConfigDict(env_prefix="LITELLM_", extra="ignore")

    enabled: bool = Field(
        default=False,
        description="Включить LiteLLM-шлюз. Default-OFF в MVP.",
    )
    default_model: str = Field(
        default="gpt-4o-mini",
        description="Модель по умолчанию (litellm-slug, напр. 'openai/gpt-4o-mini').",
    )
    fallback_models: list[str] = Field(
        default_factory=list,
        description="Цепочка fallback-моделей при недоступности основной.",
    )
    cost_tracking: bool = Field(
        default=True,
        description="Отправлять cost через CostTrackingCallback в AgentMetricsService.",
    )
    num_retries: int = Field(
        default=2, ge=0, le=10, description="Кол-во retry на transient-ошибки."
    )
    request_timeout: float = Field(
        default=60.0, ge=1.0, description="Таймаут одного запроса (сек)."
    )
    langfuse_callback: bool = Field(
        default=False, description="Подключить Langfuse-callback (если установлен)."
    )


class RagCacheSettings(BaseSettingsWithLoader):
    """3-tier RAG cache (L1 exact, L2 semantic, L3 retrieval)."""

    yaml_group: ClassVar[str] = "rag_cache"
    model_config = SettingsConfigDict(env_prefix="RAG_CACHE_", extra="ignore")

    l1_enabled: bool = Field(
        default=True,
        description="L1 exact KV cache (Redis prefix rag:l1:).",
    )
    l1_ttl: int = Field(
        default=3600, ge=1, description="TTL L1 KV-кэша (секунды)."
    )
    l2_enabled: bool = Field(
        default=False,
        description="L2 semantic cache по эмбеддингам (Qdrant). Default-OFF в MVP.",
    )
    l2_threshold: float = Field(
        default=0.92,
        ge=0.0,
        le=1.0,
        description="Минимальная косинусная похожесть для L2-hit.",
    )
    l2_collection: str = Field(
        default="rag_cache_l2",
        description="Имя коллекции Qdrant для L2.",
    )
    l3_enabled: bool = Field(
        default=True,
        description="L3 retrieval-cache (Redis prefix rag:l3:).",
    )
    l3_ttl: int = Field(
        default=600, ge=1, description="TTL L3 retrieval-кэша (секунды)."
    )
    invalidation_channel: str = Field(
        default="rag:invalidation",
        description="Redis pub/sub-канал для invalidate_by_tag.",
    )
    warm_on_ingest: bool = Field(
        default=False,
        description="Прогревать L1/L2/L3 cache на ingest (×2 cost — default-OFF).",
    )


class RagIngestSettings(BaseSettingsWithLoader):
    """Параметры RAG ingest-pipeline (D.2 / Track D)."""

    yaml_group: ClassVar[str] = "rag_ingest"
    model_config = SettingsConfigDict(env_prefix="RAG_INGEST_", extra="ignore")

    deferred: bool = Field(
        default=False,
        description="Очередить ingest в TaskIQ-broker вместо inline-исполнения.",
    )
    state_backend: str = Field(
        default="memory",
        description="Backend для IngestStateStore: 'memory' | 'redis'.",
    )
    chunker_fingerprint_version: int = Field(
        default=1,
        ge=1,
        description="Версия chunker-конфигурации для detect re-embed.",
    )
    state_ttl_seconds: int = Field(
        default=86_400, ge=60, description="TTL Redis-ключей со state ingest-задач."
    )


class BGESettings(BaseSettingsWithLoader):
    """Параметры BGE-M3 (dense embeddings) + bge-reranker-v2-m3."""

    yaml_group: ClassVar[str] = "bge"
    model_config = SettingsConfigDict(env_prefix="BGE_", extra="ignore")

    enabled: bool = Field(
        default=False,
        description="Включить BGE-провайдер (lazy-load модели на первом запросе).",
    )
    embedding_model: str = Field(
        default="BAAI/bge-m3",
        description="Имя модели BGE-M3 (1024-dim dense).",
    )
    reranker_model: str = Field(
        default="BAAI/bge-reranker-v2-m3",
        description="Имя cross-encoder reranker-модели.",
    )
    cache_dir: str = Field(
        default="./var/bge_cache",
        description="Каталог кэша HuggingFace для весов.",
    )
    use_fp16: bool = Field(
        default=True,
        description="Использовать FP16 при инициализации (экономия памяти).",
    )


class LangMemSettings(BaseSettingsWithLoader):
    """LangMem long-term memory (episodic / semantic / procedural)."""

    yaml_group: ClassVar[str] = "langmem"
    model_config = SettingsConfigDict(env_prefix="LANGMEM_", extra="ignore")

    enabled: bool = Field(
        default=False,
        description="Включить LangMem-сервис. Default-OFF в MVP.",
    )
    pg_dsn: str = Field(
        default="",
        description="DSN Postgres для episodic/procedural таблиц (если пусто, "
        "используется shared async-engine из core.config.database).",
    )
    qdrant_collection: str = Field(
        default="langmem_semantic",
        description="Коллекция Qdrant для semantic-фактов.",
    )
    consolidation_batch_size: int = Field(
        default=50,
        ge=1,
        description="Размер батча для ConsolidationEngine.run.",
    )
    consolidation_schedule_cron: str = Field(
        default="",
        description="Cron-выражение для авто-консолидации (пусто = manual only).",
    )
    consolidation_min_cluster_size: int = Field(
        default=3,
        ge=2,
        description="Минимум эпизодов в кластере (session_id+tenant) для LLM-summarize.",
    )
    consolidation_confidence_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Минимальная confidence факта для записи в semantic.",
    )
    rlm_enabled: bool = Field(
        default=False,
        description="Включить RLM (Reinforcement Learning from Memory) re-ranking.",
    )
    rlm_boost_factor: float = Field(
        default=0.1,
        ge=0.0,
        le=1.0,
        description="Множитель для feedback-induced boost/penalty (0.0=disable).",
    )
    rlm_reindex_threshold: int = Field(
        default=3,
        ge=1,
        description="Сколько 'bad' events на источник для reindex-hint.",
    )


class LangFuseSettings(BaseSettingsWithLoader):
    """Параметры LangFuse cost-tracking (D.5)."""

    yaml_group: ClassVar[str] = "langfuse"
    model_config = SettingsConfigDict(env_prefix="LANGFUSE_", extra="ignore")

    enabled: bool = Field(
        default=False,
        description="Включить LangFuse-callback и LangFuse-reader.",
    )
    host: str = Field(default="", description="LangFuse host URL.")
    public_key: str = Field(default="", description="LangFuse public key.")
    secret_key: str = Field(default="", description="LangFuse secret key.")
    flush_at: int = Field(
        default=15, ge=1, description="Batch size для async flush callback'а."
    )
    deep_link_base: str = Field(
        default="",
        description="Базовый URL для построения deep-link в UI LangFuse.",
    )


class McpSettings(BaseSettingsWithLoader):
    """Параметры FastMCP HTTP transport (D.4)."""

    yaml_group: ClassVar[str] = "mcp"
    model_config = SettingsConfigDict(env_prefix="MCP_", extra="ignore")

    http_enabled: bool = Field(
        default=False, description="Монтировать /mcp как ASGI sub-app."
    )
    bind_path: str = Field(
        default="/mcp", description="Path-prefix для FastMCP ASGI app."
    )
    auth_methods: list[str] = Field(
        default_factory=lambda: ["api_key", "jwt"],
        description="Допустимые методы: api_key, jwt.",
    )
    legacy_description_schema: bool = Field(
        default=False,
        description="Сохранять JSON-Schema в description (graceful migration).",
    )


class StreamingLLMSettings(BaseSettingsWithLoader):
    """Параметры token-level стриминга LLM через SSE / WS / Webhook."""

    yaml_group: ClassVar[str] = "streaming_llm"
    model_config = SettingsConfigDict(env_prefix="STREAMING_LLM_", extra="ignore")

    chunk_size: int = Field(
        default=1, ge=1, le=64, description="Сколько token-chunks буферизовать перед flush."
    )
    cancel_on_disconnect: bool = Field(
        default=True,
        description="Отменять upstream-stream при разрыве клиентского соединения "
        "(CancelledError → stream.aclose()).",
    )
    webhook_chunk_timeout: float = Field(
        default=5.0,
        ge=0.1,
        description="Таймаут отправки одного chunk в webhook-publisher.",
    )


litellm_gateway_settings = LiteLLMGatewaySettings()
rag_cache_settings = RagCacheSettings()
rag_ingest_settings = RagIngestSettings()
bge_settings = BGESettings()
langmem_settings = LangMemSettings()
streaming_llm_settings = StreamingLLMSettings()
langfuse_settings = LangFuseSettings()
mcp_settings = McpSettings()
