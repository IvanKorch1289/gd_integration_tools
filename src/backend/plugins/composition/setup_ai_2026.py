"""Composition setup AI Stack 2026 (К4 MVP, Шаг 8).

Регистрирует все компоненты Шагов 1–6 через single hook
``register_ai_2026_providers()``. Каждая регистрация обёрнута в
``try/except`` — отсутствующая опциональная зависимость не блокирует
старт. Default-OFF: при ``LITELLM_ENABLED=false`` etc. реальный объект
не инстанциируется и не пишется в app.state.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

__all__ = ("register_ai_2026_providers",)


async def register_ai_2026_providers() -> None:
    """Регистрирует AI-2026 компоненты в providers_registry / app.state."""
    from src.backend.core.config.ai_2026 import (
        bge_settings,
        langmem_settings,
        litellm_gateway_settings,
        rag_cache_settings,
    )
    from src.backend.core.di.app_state import get_app_ref
    from src.backend.core.providers_registry import register_provider

    app = get_app_ref()

    if litellm_gateway_settings.enabled:
        try:
            from src.backend.services.ai.gateway.client import LiteLLMGateway
            from src.backend.services.ai.model_registry import LocalFSModelRegistry

            # W2: Model Registry для dynamic routing
            model_registry = LocalFSModelRegistry()
            gateway = LiteLLMGateway(model_registry=model_registry)
            if app is not None:
                app.state.litellm_gateway = gateway
                app.state.local_fs_model_registry = model_registry
            register_provider("llm_gateway", "litellm", gateway)
            register_provider("model_registry", "local_fs", model_registry)
        except Exception as exc:  # noqa: BLE001
            logger.debug("LiteLLMGateway registration skipped: %s", exc)

    try:
        from src.backend.infrastructure.cache.rag.exact import L1ExactCache
        from src.backend.infrastructure.cache.rag.invalidation import RagInvalidationBus
        from src.backend.infrastructure.cache.rag.retrieval import L3RetrievalCache
        from src.backend.infrastructure.cache.rag.semantic import L2SemanticRagCache
        from src.backend.infrastructure.cache.rag.three_tier import ThreeTierRagCache

        l2_qdrant: object | None = None
        l2_embedder: object | None = None
        if rag_cache_settings.l2_enabled:
            try:
                from src.backend.infrastructure.clients.storage.vector_store import (
                    get_vector_store,
                )

                l2_qdrant = get_vector_store()
            except Exception as exc:  # noqa: BLE001
                logger.debug("L2 qdrant client injection skipped: %s", exc)
            try:
                from src.backend.services.ai.embedding_providers import (
                    get_embedding_provider,
                )

                l2_embedder = get_embedding_provider()
            except Exception as exc:  # noqa: BLE001
                logger.debug("L2 embedder injection skipped: %s", exc)

        bus = RagInvalidationBus(channel=rag_cache_settings.invalidation_channel)
        cache = ThreeTierRagCache(
            l1=L1ExactCache(ttl_seconds=rag_cache_settings.l1_ttl),
            l2=L2SemanticRagCache(
                qdrant_client=l2_qdrant,
                embedder=l2_embedder,
                collection=rag_cache_settings.l2_collection,
                threshold=rag_cache_settings.l2_threshold,
            ),
            l3=L3RetrievalCache(ttl_seconds=rag_cache_settings.l3_ttl),
            bus=bus,
            l1_enabled=rag_cache_settings.l1_enabled,
            l2_enabled=rag_cache_settings.l2_enabled,
            l3_enabled=rag_cache_settings.l3_enabled,
        )
        if rag_cache_settings.l2_enabled or rag_cache_settings.l3_enabled:
            await bus.start()
        if app is not None:
            app.state.three_tier_rag_cache = cache
            app.state.rag_invalidation_bus = bus
        register_provider("rag_cache", "three_tier", cache)
    except Exception as exc:  # noqa: BLE001
        logger.debug("ThreeTierRagCache registration skipped: %s", exc)

    if bge_settings.enabled:
        try:
            from src.backend.services.ai.embedding_providers_bge import (
                BGEM3EmbeddingProvider,
                BGERerankerV2M3,
            )
            from src.backend.services.ai.embedding_registry import (
                get_embedding_registry,
            )

            registry = get_embedding_registry()
            registry.register(
                "bge-m3",
                lambda: BGEM3EmbeddingProvider(
                    model_name=bge_settings.embedding_model,
                    cache_dir=bge_settings.cache_dir,
                    use_fp16=bge_settings.use_fp16,
                ),
            )
            register_provider(
                "reranker",
                "bge-v2-m3",
                BGERerankerV2M3(
                    model_name=bge_settings.reranker_model,
                    cache_dir=bge_settings.cache_dir,
                    use_fp16=bge_settings.use_fp16,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("BGE registration skipped: %s", exc)

    if langmem_settings.enabled:
        try:
            from src.backend.services.ai.langmem_service import LangMemService

            service = LangMemService(enabled=True)
            if app is not None:
                app.state.langmem_service = service
            register_provider("memory", "langmem", service)
        except Exception as exc:  # noqa: BLE001
            logger.debug("LangMemService registration skipped: %s", exc)

    # ─── PII Tokenizer (Wave S25 W4, ADR-0068) ───
    try:
        from src.backend.core.config.features import feature_flags

        if feature_flags.ai_pii_tokenizer_enabled:
            import asyncio as _asyncio

            from src.backend.core.di.providers import get_pii_tokenizer_provider
            from src.backend.core.utils.task_registry import get_task_registry

            tokenizer = get_pii_tokenizer_provider()
            if app is not None:
                app.state.pii_tokenizer = tokenizer
            register_provider("security", "pii_tokenizer", tokenizer)

            async def _pii_tokenizer_cleanup_loop() -> None:
                """Фоновый cleanup expired TokenMap (observability в Redis TTL)."""
                while True:
                    try:
                        await tokenizer.cleanup_expired(ttl_s=3600)
                    except Exception as cleanup_exc:  # noqa: BLE001
                        logger.debug(
                            "pii_tokenizer cleanup tick failed: %s", cleanup_exc
                        )
                    await _asyncio.sleep(900)

            try:
                task_registry = get_task_registry()
                task_registry.create_task(
                    _pii_tokenizer_cleanup_loop(),
                    name="pii-tokenizer-cleanup",
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "pii_tokenizer cleanup loop registration skipped: %s", exc
                )
    except Exception as exc:  # noqa: BLE001
        logger.debug("PIITokenizer registration skipped: %s", exc)


    try:
        from src.backend.dsl.engine.processors.streaming_llm import (
            TokenStreamLLMProcessor,
        )

        try:
            from src.backend.dsl.engine.plugin_registry import (
                get_processor_plugin_registry,
            )

            preg = get_processor_plugin_registry()
            register_class = getattr(preg, "register_class", None)
            if register_class is not None:
                register_class("token_stream_llm", TokenStreamLLMProcessor)
        except Exception as exc:  # noqa: BLE001
            logger.debug("TokenStreamLLM processor registration skipped: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.debug("TokenStreamLLM import skipped: %s", exc)

    logger.info("AI 2026 providers registered (default-disabled flags respected)")
