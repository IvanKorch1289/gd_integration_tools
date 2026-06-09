"""Protocol provider registration (S82 W1, lifecycle decomposition).

Извлечён из ``src/backend/plugins/composition/lifecycle.py``
(1142 LOC monolith). ADR-0105 plan: extract 5 concerns → 5 modules,
keeping ``lifespan`` orchestrator в ``lifecycle/__init__.py``.

S82 W1 scope: ТОЛЬКО ``_register_protocol_providers`` (175 LOC).
Остальные concerns (storage, cache, resilience, v11, watchers) — W2+.
"""

from __future__ import annotations

from src.backend.infrastructure.logging.factory import get_logger

app_logger = get_logger("application")

__all__ = ("register_protocol_providers",)


async def register_protocol_providers() -> None:
    """Регистрирует известные реализации Protocol'ов в providers_registry.

    Выполняется один раз при startup'е. Реестр делает реализации доступными
    для бизнес-кода через ``get_provider(category, name)`` без прямого импорта
    конкретных классов — что позволяет подменять их в тестах и hot-swap в prod.

    Каждая регистрация обёрнута в ``try/except ImportError`` — если
    соответствующая опциональная зависимость не установлена (например, нет
    ollama или langfuse), провайдер просто не регистрируется.
    """
    from src.backend.core.providers_registry import register_provider

    # LLM провайдеры (работают если есть env-переменные с ключами).
    try:
        from src.backend.services.ai.ai_providers import (
            ClaudeProvider,
            GeminiProvider,
            OllamaProvider,
            OpenAIProvider,
        )

        register_provider("llm", "openai", OpenAIProvider())
        register_provider("llm", "claude", ClaudeProvider())
        register_provider("llm", "gemini", GeminiProvider())
        register_provider("llm", "ollama", OllamaProvider())
    except Exception as exc:
        app_logger.debug("LLM providers registration skipped: %s", exc)

    # Exporters — каждый формат как отдельный Protocol-instance в категории.
    # Позволяет бизнес-коду делать get_provider("exporter", "csv") и
    # подменять реализации (csv-по-другому, xlsx-через polars и т.п.).
    try:
        from src.backend.services.io.export_service import (
            CsvExporter,
            ExcelExporter,
            JsonExporter,
            ParquetExporter,
            PdfExporter,
        )

        register_provider("exporter", "csv", CsvExporter())
        register_provider("exporter", "xlsx", ExcelExporter())
        register_provider("exporter", "pdf", PdfExporter())
        register_provider("exporter", "json", JsonExporter())
        register_provider("exporter", "parquet", ParquetExporter())
    except Exception as exc:
        app_logger.debug("Exporter registration skipped: %s", exc)

    # Agent memory (MongoDB-backed, Wave 0.10).
    try:
        from src.backend.services.ai.agent_memory import get_agent_memory_service

        memory_service = get_agent_memory_service()
        await memory_service.ensure_indexes()
        register_provider("memory", "mongo", memory_service)
    except Exception as exc:
        app_logger.debug("Memory backend registration skipped: %s", exc)

    # Wave 9: ensure_indexes для остальных Mongo-коллекций.
    try:
        from src.backend.services.notebooks import get_notebook_service

        await get_notebook_service().ensure_indexes()
    except Exception as exc:
        app_logger.debug("Notebooks ensure_indexes skipped: %s", exc)

    try:
        from src.backend.services.ai.feedback.repository import get_feedback_repository

        repo = get_feedback_repository()
        ensure = getattr(repo, "ensure_indexes", None)
        if ensure is not None:
            await ensure()
    except Exception as exc:
        app_logger.debug("ai_feedback ensure_indexes skipped: %s", exc)

    try:
        from src.backend.infrastructure.repositories.connector_configs_mongo import (
            get_connector_config_store,
        )

        await get_connector_config_store().ensure_indexes()
    except Exception as exc:
        app_logger.debug("connector_configs ensure_indexes skipped: %s", exc)

    try:
        from src.backend.infrastructure.repositories.express_dialogs_mongo import (
            get_express_dialog_store,
        )
        from src.backend.infrastructure.repositories.express_sessions_mongo import (
            get_express_session_store,
        )

        await get_express_dialog_store().ensure_indexes()
        await get_express_session_store().ensure_indexes()
    except Exception as exc:
        app_logger.debug("express stores ensure_indexes skipped: %s", exc)

    # Wave 9.3: индексы Elasticsearch для logs/orders.
    try:
        from src.backend.services.io.indexers import get_log_indexer, get_order_indexer

        await get_log_indexer().ensure_index()
        await get_order_indexer().ensure_index()
    except Exception as exc:
        app_logger.debug("ES indexers ensure_index skipped: %s", exc)

    # Wave 8.3: ensure 4 индексов для facets/aggregations API
    # (audit_logs / orders / documents / rag_chunks).
    try:
        from src.backend.infrastructure.clients.storage.elasticsearch import (
            get_elasticsearch_client,
        )

        await get_elasticsearch_client().ensure_indices(
            ["audit_logs", "orders", "documents", "rag_chunks"]
        )
    except Exception as exc:
        app_logger.debug("ES ensure_indices (4 facets) skipped: %s", exc)

    # Notification channels — каждый канал отдельно через адаптер.
    try:
        from src.backend.infrastructure.notifications.gateway import get_gateway
        from src.backend.services.ops.notification_adapters import (
            EmailNotificationAdapter,
            ExpressNotificationAdapter,
            TelegramNotificationAdapter,
            WebhookNotificationAdapter,
        )
        from src.backend.services.ops.notification_hub import get_notification_hub

        register_provider("notifier", "email", EmailNotificationAdapter())
        register_provider("notifier", "express", ExpressNotificationAdapter())
        register_provider("notifier", "telegram", TelegramNotificationAdapter())
        register_provider("notifier", "webhook", WebhookNotificationAdapter())
        # hub — мультиплексор, полезно иметь как отдельную реализацию.
        register_provider("notifier", "hub", get_notification_hub())
        # gateway — единый фасад для services/ops/notify_actions и
        # services/health/alert_subscriber (см. W6.3).
        register_provider("notifier", "gateway", get_gateway())
    except Exception as exc:
        app_logger.debug("Notifier registration skipped: %s", exc)

    # EventBus — для services/health/alert_subscriber и др. подписчиков.
    try:
        from src.backend.infrastructure.clients.messaging.event_bus import get_event_bus

        register_provider("event_bus", "default", get_event_bus())
    except Exception as exc:
        app_logger.debug("EventBus registration skipped: %s", exc)

    # Prompt store (in-memory fallback, при наличии LangFuse — он приоритетен).
    try:
        from src.backend.services.ai.prompt_registry import get_prompt_registry

        register_provider("prompt_store", "default", get_prompt_registry())
    except Exception as exc:
        app_logger.debug("Prompt store registration skipped: %s", exc)

    # К4 MVP (Sprint S5): AI Stack 2026 single-hook регистрация.
    try:
        from src.backend.plugins.composition.setup_ai_2026 import (
            register_ai_2026_providers,
        )

        await register_ai_2026_providers()
    except Exception as exc:
        app_logger.debug("AI 2026 providers registration skipped: %s", exc)

    from src.backend.core.providers_registry import list_providers

    app_logger.info("Protocol providers registered: %s", list_providers())
