from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.infrastructure.external_apis.logging_service import app_logger

__all__ = ("lifespan",)


async def _register_protocol_providers() -> None:
    """Регистрирует известные реализации Protocol'ов в providers_registry.

    Выполняется один раз при startup'е. Реестр делает реализации доступными
    для бизнес-кода через ``get_provider(category, name)`` без прямого импорта
    конкретных классов — что позволяет подменять их в тестах и hot-swap в prod.

    Каждая регистрация обёрнута в ``try/except ImportError`` — если
    соответствующая опциональная зависимость не установлена (например, нет
    ollama или langfuse), провайдер просто не регистрируется.
    """
    from src.core.providers_registry import register_provider

    # LLM провайдеры (работают если есть env-переменные с ключами).
    try:
        from src.services.ai.ai_providers import (
            ClaudeProvider,
            GeminiProvider,
            OllamaProvider,
            OpenAIProvider,
        )

        register_provider("llm", "openai", OpenAIProvider())
        register_provider("llm", "claude", ClaudeProvider())
        register_provider("llm", "gemini", GeminiProvider())
        register_provider("llm", "ollama", OllamaProvider())
    except Exception as exc:  # noqa: BLE001
        app_logger.debug("LLM providers registration skipped: %s", exc)

    # Exporters — каждый формат как отдельный Protocol-instance в категории.
    # Позволяет бизнес-коду делать get_provider("exporter", "csv") и
    # подменять реализации (csv-по-другому, xlsx-через polars и т.п.).
    try:
        from src.services.io.export_service import (
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
    except Exception as exc:  # noqa: BLE001
        app_logger.debug("Exporter registration skipped: %s", exc)

    # Agent memory (MongoDB-backed, Wave 0.10).
    try:
        from src.services.ai.agent_memory import get_agent_memory_service

        memory_service = get_agent_memory_service()
        await memory_service.ensure_indexes()
        register_provider("memory", "mongo", memory_service)
    except Exception as exc:  # noqa: BLE001
        app_logger.debug("Memory backend registration skipped: %s", exc)

    # Wave 9: ensure_indexes для остальных Mongo-коллекций.
    try:
        from src.services.notebooks import get_notebook_service

        await get_notebook_service().ensure_indexes()
    except Exception as exc:  # noqa: BLE001
        app_logger.debug("Notebooks ensure_indexes skipped: %s", exc)

    try:
        from src.services.ai.feedback.repository import get_feedback_repository

        repo = get_feedback_repository()
        ensure = getattr(repo, "ensure_indexes", None)
        if ensure is not None:
            await ensure()
    except Exception as exc:  # noqa: BLE001
        app_logger.debug("ai_feedback ensure_indexes skipped: %s", exc)

    try:
        from src.infrastructure.workflow.state_projector import (
            get_workflow_state_projector,
        )

        await get_workflow_state_projector().ensure_indexes()
    except Exception as exc:  # noqa: BLE001
        app_logger.debug("workflow_state ensure_indexes skipped: %s", exc)

    try:
        from src.infrastructure.repositories.connector_configs_mongo import (
            get_connector_config_store,
        )

        await get_connector_config_store().ensure_indexes()
    except Exception as exc:  # noqa: BLE001
        app_logger.debug("connector_configs ensure_indexes skipped: %s", exc)

    try:
        from src.infrastructure.repositories.express_dialogs_mongo import (
            get_express_dialog_store,
        )
        from src.infrastructure.repositories.express_sessions_mongo import (
            get_express_session_store,
        )

        await get_express_dialog_store().ensure_indexes()
        await get_express_session_store().ensure_indexes()
    except Exception as exc:  # noqa: BLE001
        app_logger.debug("express stores ensure_indexes skipped: %s", exc)

    # Wave 9.3: индексы Elasticsearch для logs/orders.
    try:
        from src.services.io.indexers import get_log_indexer, get_order_indexer

        await get_log_indexer().ensure_index()
        await get_order_indexer().ensure_index()
    except Exception as exc:  # noqa: BLE001
        app_logger.debug("ES indexers ensure_index skipped: %s", exc)

    # Notification channels — каждый канал отдельно через адаптер.
    try:
        from src.infrastructure.notifications.gateway import get_gateway
        from src.services.ops.notification_adapters import (
            EmailNotificationAdapter,
            ExpressNotificationAdapter,
            TelegramNotificationAdapter,
            WebhookNotificationAdapter,
        )
        from src.services.ops.notification_hub import get_notification_hub

        register_provider("notifier", "email", EmailNotificationAdapter())
        register_provider("notifier", "express", ExpressNotificationAdapter())
        register_provider("notifier", "telegram", TelegramNotificationAdapter())
        register_provider("notifier", "webhook", WebhookNotificationAdapter())
        # hub — мультиплексор, полезно иметь как отдельную реализацию.
        register_provider("notifier", "hub", get_notification_hub())
        # gateway — единый фасад для services/ops/notify_actions и
        # services/health/alert_subscriber (см. W6.3).
        register_provider("notifier", "gateway", get_gateway())
    except Exception as exc:  # noqa: BLE001
        app_logger.debug("Notifier registration skipped: %s", exc)

    # EventBus — для services/health/alert_subscriber и др. подписчиков.
    try:
        from src.infrastructure.clients.messaging.event_bus import get_event_bus

        register_provider("event_bus", "default", get_event_bus())
    except Exception as exc:  # noqa: BLE001
        app_logger.debug("EventBus registration skipped: %s", exc)

    # Prompt store (in-memory fallback, при наличии LangFuse — он приоритетен).
    try:
        from src.services.ai.prompt_registry import get_prompt_registry

        register_provider("prompt_store", "default", get_prompt_registry())
    except Exception as exc:  # noqa: BLE001
        app_logger.debug("Prompt store registration skipped: %s", exc)

    from src.core.providers_registry import list_providers

    app_logger.info("Protocol providers registered: %s", list_providers())


def _register_storage_singletons(app: FastAPI) -> None:
    """Регистрирует Mongo-реализации репозиториев в ``app.state`` (W6).

    Bootstrap-точка для Mongo-backends: services/ai/feedback/repository.py
    и services/notebooks/service.py обращаются к ``app.state.*`` через
    ``app_state_singleton``; конкретный backend ставится здесь.
    """
    try:
        from src.infrastructure.repositories.ai_feedback_mongo import (
            MongoFeedbackRepository,
        )

        app.state.ai_feedback_repository = MongoFeedbackRepository()
    except Exception as exc:  # noqa: BLE001
        app_logger.debug("MongoFeedbackRepository registration skipped: %s", exc)

    try:
        from src.infrastructure.repositories.notebooks_mongo import (
            MongoNotebookRepository,
        )
        from src.services.notebooks.service import NotebookService

        app.state.notebook_service = NotebookService(MongoNotebookRepository())
    except Exception as exc:  # noqa: BLE001
        app_logger.debug("MongoNotebookRepository registration skipped: %s", exc)

    try:
        from src.infrastructure.clients.storage.vector_store import get_vector_store
        from src.services.ai.rag_service import RAGService

        app.state.rag_service = RAGService(store=get_vector_store())
    except Exception as exc:  # noqa: BLE001
        app_logger.debug("RAGService registration skipped: %s", exc)

    try:
        from src.infrastructure.clients.storage.elasticsearch import (
            get_elasticsearch_client,
        )
        from src.services.io.search import SearchService

        app.state.search_service = SearchService(client=get_elasticsearch_client())
    except Exception as exc:  # noqa: BLE001
        app_logger.debug("SearchService registration skipped: %s", exc)


def _validate_cache_layers() -> None:
    """Проверяет отсутствие двойного кэширования (ADR-004) на старте.

    Использует глобальный ``cache_config_registry`` из
    ``src.infrastructure.cache``. Каждый сервис/репозиторий, включающий
    кэш, обязан зарегистрироваться в этом реестре через
    ``cache_config_registry.register(entity=..., layer=..., enabled=True)``.

    При обнаружении конфликта падаем fail-fast с ``CacheDuplicationError``
    — лучше не запустить приложение, чем работать с неконсистентной
    инвалидацией кэша.
    """
    from src.infrastructure.cache import cache_config_registry
    from src.infrastructure.cache.validator import CacheLayerValidator

    CacheLayerValidator().validate(cache_config_registry)
    app_logger.info(
        "Cache layer validation passed (ADR-004). Entries: %d",
        len(cache_config_registry.entries),
    )


def _bootstrap_snapshot_job(app: FastAPI) -> None:
    """W26.8 — initial PG → SQLite sync + регистрация interval-job'а.

    Initial sync необходим для холодного старта (snapshot-файл ещё
    отсутствует), interval-job — для последующего регулярного refresh'а.
    Оба шага опциональны: ошибки не блокируют startup (fallback продолжит
    работать на устаревшем файле; alert придёт через метрику
    ``snapshot_age_seconds``).
    """
    try:
        from src.core.config.settings import settings as app_settings

        if not app_settings.snapshot.enabled:
            app_logger.info(
                "Snapshot job отключён (snapshot.enabled=false), пропуск bootstrap"
            )
            return

        from src.infrastructure.resilience.snapshot_job import (
            register_snapshot_job,
            run_snapshot_now,
        )
        from src.infrastructure.scheduler.scheduler_manager import scheduler_manager

        if app_settings.snapshot.run_on_startup:
            try:
                run_snapshot_now()
            except Exception as exc:  # noqa: BLE001
                app_logger.warning(
                    "Initial PG → SQLite snapshot failed (продолжаем с stale-файлом): %s",
                    exc,
                )

        register_snapshot_job(scheduler_manager.scheduler)
    except Exception as exc:  # noqa: BLE001
        app_logger.warning("Snapshot job bootstrap skipped: %s", exc)


def _bootstrap_resilience_coordinator(app: FastAPI) -> None:
    """W26.1/W26.2 — регистрирует 11 компонентов в ``ResilienceCoordinator``
    и подключает их к ``HealthAggregator``.

    На этапе W26.1 backend'ы — stubs (``NotImplementedError``); цель —
    чтобы health-check matrix (W26.2) сразу видела весь список из 11
    компонентов. Реальные wiring'и подставляются в W26.3/W26.4.
    """
    try:
        from src.core.config.settings import settings as app_settings
        from src.infrastructure.application.health_aggregator import (
            get_health_aggregator,
        )
        from src.infrastructure.resilience.coordinator import get_resilience_coordinator
        from src.infrastructure.resilience.health import (
            register_resilience_health_checks,
        )
        from src.infrastructure.resilience.registration import register_all_components

        coordinator = get_resilience_coordinator()
        register_all_components(coordinator, app_settings.resilience)
        register_resilience_health_checks(get_health_aggregator(), coordinator)
        app.state.resilience_coordinator = coordinator
    except Exception as exc:  # noqa: BLE001
        app_logger.warning("ResilienceCoordinator bootstrap skipped: %s", exc)


async def _start_dsl_yaml_watcher(app: FastAPI) -> None:
    """W25.1 — поднимает ``DSLYamlWatcher`` под флагом dsl.hot_reload_enabled.

    Watcher отслеживает ``dsl_routes/`` и атомарно перезагружает Pipeline'ы
    при изменении файлов. На dev_light/тестах флаг по умолчанию выключен —
    startup продолжается без watcher'а.
    """
    from src.core.config.settings import settings as app_settings

    if not app_settings.dsl.hot_reload_enabled:
        app_logger.info("DSL hot-reload disabled (DSL_HOT_RELOAD_ENABLED=false)")
        return

    try:
        from src.dsl.commands.registry import route_registry
        from src.dsl.yaml_watcher import DSLYamlWatcher

        watcher = DSLYamlWatcher(
            routes_dir=app_settings.dsl.routes_dir,
            route_registry=route_registry,
            debounce_ms=app_settings.dsl.hot_reload_debounce_ms,
        )
        await watcher.start()
        app.state.dsl_yaml_watcher = watcher
    except Exception as exc:  # noqa: BLE001
        app_logger.warning("DSLYamlWatcher startup skipped: %s", exc)


async def _stop_dsl_yaml_watcher(app: FastAPI) -> None:
    """Останавливает ``DSLYamlWatcher`` если он был запущен."""
    watcher = getattr(app.state, "dsl_yaml_watcher", None)
    if watcher is None:
        return
    try:
        await watcher.stop()
    except Exception as exc:  # noqa: BLE001
        app_logger.warning("DSLYamlWatcher shutdown error: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Управляет жизненным циклом приложения FastAPI.
    """
    from src.dsl.commands.setup import register_action_handlers
    from src.dsl.routes import register_dsl_routes
    from src.plugins.composition.service_setup import register_all_services
    from src.plugins.composition.setup_infra import ending, starting

    app_logger.info("Запуск приложения...")
    startup_completed = False

    try:
        from src.plugins.composition.di import register_app_state

        register_app_state(app)
        _register_storage_singletons(app)

        register_all_services()
        register_action_handlers()
        register_dsl_routes()
        _bootstrap_resilience_coordinator(app)
        _bootstrap_snapshot_job(app)
        await _start_dsl_yaml_watcher(app)
        await starting()
        await _register_protocol_providers()
        _validate_cache_layers()

        try:
            from src.workflows.outbox_worker import start_outbox_worker

            start_outbox_worker(interval_seconds=5, batch_size=100)
        except Exception as exc:  # noqa: BLE001
            # Outbox-worker не критичен для базовой работоспособности
            # (например, dev_light без RabbitMQ) — startup продолжается.
            app_logger.warning("Outbox worker registration skipped: %s", exc)

        startup_completed = True
        app.state.infrastructure_ready = True

        from src.dsl.commands.registry import action_handler_registry
        from src.dsl.registry import route_registry

        app_logger.info(
            "Приложение успешно запущено: %d actions, %d DSL-маршрутов",
            len(action_handler_registry.list_actions()),
            len(route_registry.list_routes()),
        )
        yield

    except Exception as exc:
        if not startup_completed:
            app_logger.critical(
                "Критическая ошибка при запуске приложения: %s", str(exc), exc_info=True
            )
            raise RuntimeError(
                "Остановка приложения из-за ошибки инициализации"
            ) from exc

        app_logger.critical(
            "Критическая ошибка во время работы приложения: %s", str(exc), exc_info=True
        )
        raise

    finally:
        app_logger.info("Завершение работы приложения...")
        app.state.infrastructure_ready = False

        await _stop_dsl_yaml_watcher(app)

        try:
            from src.workflows.outbox_worker import stop_outbox_worker

            await stop_outbox_worker()
        except Exception as worker_exc:  # noqa: BLE001
            app_logger.warning("Ошибка остановки outbox worker: %s", worker_exc)

        try:
            await ending()
        except Exception as shutdown_exc:
            app_logger.error(
                "Ошибка при завершении работы приложения: %s",
                str(shutdown_exc),
                exc_info=True,
            )

        app_logger.info("Приложение остановлено")
