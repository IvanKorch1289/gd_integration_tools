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
    "BGESettings",
    "LangMemSettings",
    "StreamingLLMSettings",
    "litellm_gateway_settings",
    "rag_cache_settings",
    "bge_settings",
    "langmem_settings",
    "streaming_llm_settings",
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
bge_settings = BGESettings()
langmem_settings = LangMemSettings()
streaming_llm_settings = StreamingLLMSettings()
