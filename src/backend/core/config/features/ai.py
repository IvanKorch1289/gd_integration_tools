"""AI feature-flags (T1.3.7 split from core.config.features.__init__).

Извлечено 9 K6 — AI flags (S38 P1.1 epic, T1.3.7 PR):
- search_provider_searxng
- langmem_enabled
- mcp_tools_input_schema_strict
- langfuse_v3
- rag_cache_l2_semantic
- rag_cache_l3_retrieval
- ai_workspace_ttl_cleanup
- prompt_registry_langfuse
- multimodal_rag_enabled

Future T1.3.7.5+ extensions (Sprint 5/6/7 K4 AI sections, ~60 fields).
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AIFlags(BaseSettings):
    """K6 — AI + K4 AI/Data. Owner: K4 AI/Data, K6 AI/RAG.

    Per S38 T1.3.7, извлечено из monolithic ``core.config.features.FeatureFlags``
    для eventual multi-inheritance split (9 доменов, 10 PRs).

    Re-export в ``__init__.py``:
        from src.backend.core.config.features.ai import AIFlags
        class FeatureFlags(..., AIFlags, ...):
            ...

    Env-var prefix: ``FEATURE_`` (inherited from parent pydantic-settings config).
    """

    model_config = SettingsConfigDict(env_prefix="FEATURE_", extra="forbid")

    search_provider_searxng: bool = Field(
        default=True,
        title="Search: SearXNGProvider в WebSearchService fallback chain",
        description=(
            "K4 Wave 4 (PLAN #5). Owner: K4 AI/Data. ETA: S3-W3. "
            "Активирует SearXNGProvider в fallback chain WebSearchService — "
            "self-hosted privacy-first meta-search. Требует SEARXNG_BASE_URL env. "
            "default-OFF до развёртывания SearXNG instance в staging."
        ),
    )

    langmem_enabled: bool = Field(
        default=True,
        title="AI: LangMem long-term memory (episodic/semantic/procedural)",
        description=(
            "K6 Wave 1 (K4 LangMem baseline). Owner: K4 AI/Data. ETA: S3-W1. "
            "Активирует LangMemService в src/backend/services/ai/memory/. "
            "При False все вызовы remember_*/recall возвращают пустые результаты "
            "без записи. default-OFF до staging-smoke с Postgres + Qdrant."
        ),
    )

    mcp_tools_input_schema_strict: bool = Field(
        default=True,
        title="MCP: строгая валидация input_schema для FastMCP tools",
        description=(
            "K6 Wave 2. Owner: K6 AI/RAG. ETA: S3-W2. "
            "При True — validate_input_schema() поднимает ValidationError "
            "вместо возврата (False, msg) при несоответствии JSON-Schema. "
            "default-OFF до полного покрытия Tier 1+2 actions параметрами."
        ),
    )

    langfuse_v3: bool = Field(
        default=True,
        title="AI: LangFuse 3.x callbacks",
        description=(
            "K6 Wave 1. Owner: K6 AI/RAG. ETA: S2-W1. "
            "Переключение на LangFuse 3.x SDK. default-OFF до полной "
            "миграции callbacks и smoke на 1 trace + generation."
        ),
    )

    rag_cache_l2_semantic: bool = Field(
        default=True,
        title="AI: RAG cache L2 (semantic match через embeddings)",
        description=(
            "K6 Wave 3. Owner: K6 AI/RAG. ETA: S2-W3. "
            "Активирует L2 semantic cache layer (L1 LRU уже работает). "
            "Требует sentence-transformers (или fallback-эмбеддер) в окружении. "
            "default-ON начиная с Sprint 86; при отсутствии зависимостей "
            "кэш gracefully отключается."
        ),
    )

    rag_cache_l3_retrieval: bool = Field(
        default=True,
        title="AI: RAG cache L3 (retrieval-graph cache)",
        description=(
            "K6 Wave 3. Owner: K6 AI/RAG. ETA: S2-W3. "
            "Активирует L3 retrieval-graph cache. default-OFF до завершения "
            "L2 stabilization."
        ),
    )

    ai_workspace_ttl_cleanup: bool = Field(
        default=True,
        title="AI: TTL cleanup для ${AI_WORKSPACE}/<tenant>/<session>/",
        description=(
            "K6 Wave 4. Owner: K6 AI/RAG. ETA: S2-W4. "
            "Активирует scheduled job (7 days TTL + size quota per tenant) "
            "для AI workspace в lifespan. default-OFF до audit-event-тестов."
        ),
    )

    prompt_registry_langfuse: bool = Field(
        default=True,
        title="AI: LangfusePromptStorage как backend для prompt-registry",
        description=(
            "K4 Sprint 3 Wave 3. Owner: K4 AI/Data. ETA: S3-W3. "
            "Активирует LangfusePromptStorage — хранение и версионирование "
            "промптов через Langfuse SDK (get/save/list). "
            "При False — используется in-memory fallback (PromptEntry store). "
            "default-OFF до staging-smoke с Langfuse instance и smoke-теста "
            "на 1 prompt round-trip."
        ),
    )

    prompt_registry_gateway_wiring: bool = Field(
        default=True,
        title="AI: PromptRegistry → AIGateway wiring (Sprint 86)",
        description=(
            "При True AIGateway шаг 5 (render prompt) вызывает "
            "PromptRegistry.get_compiled() по prompt_ref до инвокации LLM. "
            "При промахе registry fallback к inline prompt. default-OFF до "
            "smoke-теста registry round-trip."
        ),
    )

    multimodal_rag_enabled: bool = Field(
        default=True,
        title="AI: MultimodalRAG (text + image + audio embeddings и retrieval)",
        description=(
            "K6 Wave 4 (K4 W4 early scaffold). Owner: K4 AI/Data. ETA: S3-W4. "
            "Активирует MultimodalRAGService: ingestion трёх модальностей "
            "(text/image/audio) и семантический retrieval с modality filter. "
            "В scaffold-версии: dummy 384-dim embeddings + in-memory store. "
            "Production: CLIP (image) + Whisper→text (audio) + BGE-M3 (text). "
            "default-OFF до ML-deps stabilization и staging-smoke."
        ),
    )


__all__ = ("AIFlags",)
