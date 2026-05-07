from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from src.backend.core.utils.task_registry import get_task_registry
from src.backend.infrastructure.external_apis.logging_service import app_logger

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
    except Exception as exc:  # noqa: BLE001
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
    except Exception as exc:  # noqa: BLE001
        app_logger.debug("Exporter registration skipped: %s", exc)

    # Agent memory (MongoDB-backed, Wave 0.10).
    try:
        from src.backend.services.ai.agent_memory import get_agent_memory_service

        memory_service = get_agent_memory_service()
        await memory_service.ensure_indexes()
        register_provider("memory", "mongo", memory_service)
    except Exception as exc:  # noqa: BLE001
        app_logger.debug("Memory backend registration skipped: %s", exc)

    # Wave 9: ensure_indexes для остальных Mongo-коллекций.
    try:
        from src.backend.services.notebooks import get_notebook_service

        await get_notebook_service().ensure_indexes()
    except Exception as exc:  # noqa: BLE001
        app_logger.debug("Notebooks ensure_indexes skipped: %s", exc)

    try:
        from src.backend.services.ai.feedback.repository import get_feedback_repository

        repo = get_feedback_repository()
        ensure = getattr(repo, "ensure_indexes", None)
        if ensure is not None:
            await ensure()
    except Exception as exc:  # noqa: BLE001
        app_logger.debug("ai_feedback ensure_indexes skipped: %s", exc)

    try:
        from src.backend.infrastructure.workflow.state_projector import (
            get_workflow_state_projector,
        )

        await get_workflow_state_projector().ensure_indexes()
    except Exception as exc:  # noqa: BLE001
        app_logger.debug("workflow_state ensure_indexes skipped: %s", exc)

    try:
        from src.backend.infrastructure.repositories.connector_configs_mongo import (
            get_connector_config_store,
        )

        await get_connector_config_store().ensure_indexes()
    except Exception as exc:  # noqa: BLE001
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
    except Exception as exc:  # noqa: BLE001
        app_logger.debug("express stores ensure_indexes skipped: %s", exc)

    # Wave 9.3: индексы Elasticsearch для logs/orders.
    try:
        from src.backend.services.io.indexers import get_log_indexer, get_order_indexer

        await get_log_indexer().ensure_index()
        await get_order_indexer().ensure_index()
    except Exception as exc:  # noqa: BLE001
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
    except Exception as exc:  # noqa: BLE001
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
    except Exception as exc:  # noqa: BLE001
        app_logger.debug("Notifier registration skipped: %s", exc)

    # EventBus — для services/health/alert_subscriber и др. подписчиков.
    try:
        from src.backend.infrastructure.clients.messaging.event_bus import get_event_bus

        register_provider("event_bus", "default", get_event_bus())
    except Exception as exc:  # noqa: BLE001
        app_logger.debug("EventBus registration skipped: %s", exc)

    # Prompt store (in-memory fallback, при наличии LangFuse — он приоритетен).
    try:
        from src.backend.services.ai.prompt_registry import get_prompt_registry

        register_provider("prompt_store", "default", get_prompt_registry())
    except Exception as exc:  # noqa: BLE001
        app_logger.debug("Prompt store registration skipped: %s", exc)

    from src.backend.core.providers_registry import list_providers

    app_logger.info("Protocol providers registered: %s", list_providers())


def _register_storage_singletons(app: FastAPI) -> None:
    """Регистрирует Mongo-реализации репозиториев в ``app.state`` (W6).

    Bootstrap-точка для Mongo-backends: services/ai/feedback/repository.py
    и services/notebooks/service.py обращаются к ``app.state.*`` через
    ``app_state_singleton``; конкретный backend ставится здесь.
    """
    try:
        from src.backend.infrastructure.repositories.ai_feedback_mongo import (
            MongoFeedbackRepository,
        )

        app.state.ai_feedback_repository = MongoFeedbackRepository()
    except Exception as exc:  # noqa: BLE001
        app_logger.debug("MongoFeedbackRepository registration skipped: %s", exc)

    try:
        from src.backend.infrastructure.repositories.notebooks_mongo import (
            MongoNotebookRepository,
        )
        from src.backend.services.notebooks.service import NotebookService

        app.state.notebook_service = NotebookService(MongoNotebookRepository())
    except Exception as exc:  # noqa: BLE001
        app_logger.debug("MongoNotebookRepository registration skipped: %s", exc)

    try:
        from src.backend.infrastructure.clients.storage.vector_store import (
            get_vector_store,
        )
        from src.backend.services.ai.rag_service import RAGService

        app.state.rag_service = RAGService(store=get_vector_store())
    except Exception as exc:  # noqa: BLE001
        app_logger.debug("RAGService registration skipped: %s", exc)

    try:
        from src.backend.infrastructure.clients.storage.elasticsearch import (
            get_elasticsearch_client,
        )
        from src.backend.services.io.search import SearchService

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
    from src.backend.infrastructure.cache import cache_config_registry
    from src.backend.infrastructure.cache.validator import CacheLayerValidator

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
        from src.backend.core.config.settings import settings as app_settings

        if not app_settings.snapshot.enabled:
            app_logger.info(
                "Snapshot job отключён (snapshot.enabled=false), пропуск bootstrap"
            )
            return

        from src.backend.infrastructure.resilience.snapshot_job import (
            register_snapshot_job,
            run_snapshot_now,
        )
        from src.backend.infrastructure.scheduler.scheduler_manager import (
            scheduler_manager,
        )

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
        from src.backend.core.config.settings import settings as app_settings
        from src.backend.infrastructure.application.health_aggregator import (
            get_health_aggregator,
        )
        from src.backend.infrastructure.resilience.coordinator import (
            get_resilience_coordinator,
        )
        from src.backend.infrastructure.resilience.health import (
            register_resilience_health_checks,
        )
        from src.backend.infrastructure.resilience.registration import (
            register_all_components,
        )

        coordinator = get_resilience_coordinator()
        register_all_components(coordinator, app_settings.resilience)
        register_resilience_health_checks(get_health_aggregator(), coordinator)
        app.state.resilience_coordinator = coordinator
    except Exception as exc:  # noqa: BLE001
        app_logger.warning("ResilienceCoordinator bootstrap skipped: %s", exc)


async def _bootstrap_v11_plugin_loader(app: FastAPI) -> None:
    """R1.fin (ADR-042/044) — поднять PluginLoaderV11 под feature-flag.

    По умолчанию выключено (``v11.plugin_loader_enabled=False``). При
    включении сканирует ``extensions/<name>/plugin.toml``, выделяет
    capabilities в ``CapabilityGate`` до import и запускает lifecycle.
    Параллельно с Wave 4.4 PluginLoader (``app.state.plugin_loader``);
    падение V11-loader не валит startup.
    """
    from src.backend.core.config.settings import settings as app_settings

    if not app_settings.v11.plugin_loader_enabled:
        app_logger.info("V11 PluginLoader disabled (V11_PLUGIN_LOADER_ENABLED=false)")
        return

    try:
        from src.backend.core.security.capabilities import CapabilityGate
        from src.backend.dsl.commands.action_registry import action_handler_registry
        from src.backend.dsl.engine.plugin_registry import get_processor_plugin_registry
        from src.backend.services.plugins.loader_v11 import PluginLoaderV11
        from src.backend.services.plugins.registries import (
            ActionRegistryAdapter,
            ProcessorRegistryAdapter,
            get_repository_hook_registry,
        )

        gate = CapabilityGate()
        loader = PluginLoaderV11(
            extensions_dir=app_settings.v11.extensions_dir,
            capability_gate=gate,
            action_registry=ActionRegistryAdapter(action_handler_registry),
            repository_registry=get_repository_hook_registry(),
            processor_registry=ProcessorRegistryAdapter(
                get_processor_plugin_registry()
            ),
            core_version=app_settings.v11.core_version,
        )
        await loader.discover_and_load()
        app.state.capability_gate = gate
        app.state.plugin_loader_v11 = loader
        app_logger.info(
            "V11 PluginLoader: %d плагин(ов) загружено", len(loader.successful)
        )
    except Exception as exc:  # noqa: BLE001
        app_logger.warning("V11 PluginLoader bootstrap skipped: %s", exc)


async def _bootstrap_v11_route_loader(app: FastAPI) -> None:
    """R1.fin (ADR-043/044) — поднять RouteLoader под feature-flag.

    По умолчанию выключено. При включении сканирует
    ``routes/<name>/route.toml``, проверяет ``requires_plugins`` через
    ранее загруженные V11-плагины (из :func:`_bootstrap_v11_plugin_loader`),
    делает invariant-check ``capabilities ⊆ plugins ∪ public-core`` и
    регистрирует pipeline-файлы через ``route_registry``.
    """
    from src.backend.core.config.settings import settings as app_settings

    if not app_settings.v11.route_loader_enabled:
        app_logger.info("V11 RouteLoader disabled (V11_ROUTE_LOADER_ENABLED=false)")
        return

    gate = getattr(app.state, "capability_gate", None)
    if gate is None:
        # RouteLoader без gate работать не может; используем чистый
        # gate (route может не использовать capabilities).
        from src.backend.core.security.capabilities import CapabilityGate

        gate = CapabilityGate()
        app.state.capability_gate = gate

    try:
        from src.backend.core.security.capabilities import build_default_vocabulary
        from src.backend.dsl.commands.registry import route_registry
        from src.backend.dsl.yaml_loader import load_pipeline_from_file
        from src.backend.services.routes.loader import InstalledPlugin, RouteLoader

        # installed_plugins из V11 PluginLoader (если поднят).
        installed: dict[str, InstalledPlugin] = {}
        v11_loader = getattr(app.state, "plugin_loader_v11", None)
        if v11_loader is not None:
            for entry in v11_loader.successful:
                if entry.manifest is None:
                    continue
                installed[entry.name] = InstalledPlugin(
                    name=entry.name,
                    version=entry.version,
                    capabilities=tuple(entry.manifest.capabilities),
                )

        def _registrar(route_name: str, pipeline_path: Path) -> None:
            """Делегирует загрузку pipeline-файла в ``route_registry``."""
            pipeline = load_pipeline_from_file(pipeline_path)
            route_registry.register(pipeline)

        loader = RouteLoader(
            routes_dir=app_settings.v11.routes_dir,
            capability_gate=gate,
            vocabulary=build_default_vocabulary(),
            core_version=app_settings.v11.core_version,
            installed_plugins=installed,
            pipeline_registrar=_registrar,
        )
        await loader.discover_and_load()
        app.state.route_loader_v11 = loader
        app_logger.info("V11 RouteLoader: %d маршрут(ов) активно", len(loader.enabled))
    except Exception as exc:  # noqa: BLE001
        app_logger.warning("V11 RouteLoader bootstrap skipped: %s", exc)


async def _shutdown_v11_loaders(app: FastAPI) -> None:
    """R1.fin — обратный порядок: сначала RouteLoader, затем PluginLoaderV11."""
    watcher_task = getattr(app.state, "v11_hot_reload_task", None)
    if watcher_task is not None and not watcher_task.done():
        watcher_task.cancel()
        try:
            await watcher_task
        except BaseException as cancel_exc:  # noqa: BLE001 — cancellation/await
            app_logger.debug("V11 hot-reload task cancelled: %s", cancel_exc)

    route_loader = getattr(app.state, "route_loader_v11", None)
    if route_loader is not None:
        try:
            await route_loader.unload_all()
        except Exception as exc:  # noqa: BLE001
            app_logger.warning("V11 RouteLoader shutdown error: %s", exc)

    plugin_loader = getattr(app.state, "plugin_loader_v11", None)
    if plugin_loader is not None:
        try:
            await plugin_loader.shutdown_all()
        except Exception as exc:  # noqa: BLE001
            app_logger.warning("V11 PluginLoader shutdown error: %s", exc)


async def _start_v11_hot_reload(app: FastAPI) -> None:
    """R1.fin — поднимает watchfiles awatch на ``extensions/`` + ``routes/``.

    Под флагом ``v11.hot_reload_enabled`` (default OFF). При file-event:

    * изменение ``plugin.toml`` — full reload плагина (сложный путь);
    * изменение ``route.toml`` — full re-register маршрута;
    * изменение ``*.dsl.yaml`` внутри ``routes/<name>/`` — pipeline-reload
      без перепроверки manifest'а.

    Реализован через единственный ``asyncio.Task`` (через TaskRegistry);
    cancel выполняется на shutdown через TaskRegistry.shutdown_all.
    Семантика debounce — наследуется из watchfiles.awatch.
    """
    from src.backend.core.config.settings import settings as app_settings

    if not app_settings.v11.hot_reload_enabled:
        app_logger.info("V11 hot-reload disabled (V11_HOT_RELOAD_ENABLED=false)")
        return

    plugin_loader = getattr(app.state, "plugin_loader_v11", None)
    route_loader = getattr(app.state, "route_loader_v11", None)
    if plugin_loader is None and route_loader is None:
        app_logger.info(
            "V11 hot-reload skipped: ни PluginLoaderV11, ни RouteLoader не активны"
        )
        return

    candidate_dirs: list[Path] = []
    if plugin_loader is not None:
        candidate_dirs.append(app_settings.v11.extensions_dir)
    if route_loader is not None:
        candidate_dirs.append(app_settings.v11.routes_dir)
    watch_dirs: list[str] = [str(p) for p in candidate_dirs if Path(p).is_dir()]
    if not watch_dirs:
        app_logger.info("V11 hot-reload: ни одного существующего каталога")
        return

    debounce_ms = app_settings.v11.hot_reload_debounce_ms

    async def _watch_loop() -> None:
        """Цикл awatch с graceful cancel."""
        from watchfiles import awatch

        async for changes in awatch(*watch_dirs, debounce=debounce_ms):
            try:
                await _handle_v11_changes(app, changes)
            except Exception as exc:  # noqa: BLE001
                app_logger.warning("V11 hot-reload handler error: %s", exc)

    task = get_task_registry().create_task(_watch_loop(), name="v11-hot-reload")
    app.state.v11_hot_reload_task = task
    app_logger.info(
        "V11 hot-reload started: watching %s (debounce=%dms)", watch_dirs, debounce_ms
    )


async def _handle_v11_changes(app: FastAPI, changes: set) -> None:
    """Обработать batch file-event'ов от watchfiles.

    Логика:
    * Любое изменение ``plugin.toml`` → re-discover (PluginLoaderV11
      идемпотентен по name; уже загруженный пропускается).
    * Любое изменение ``route.toml`` → RouteLoader.unload_all +
      discover_and_load (дёшево, всё равно ≤ 50 маршрутов).
    * ``*.dsl.yaml`` без manifest-изменений → re-load только
      затронутых route'ов.
    """
    plugin_loader = getattr(app.state, "plugin_loader_v11", None)
    route_loader = getattr(app.state, "route_loader_v11", None)

    plugin_event = any(p.endswith("plugin.toml") for _, p in changes)
    route_event = any(p.endswith("route.toml") for _, p in changes)
    pipeline_event = any(p.endswith((".dsl.yaml", ".yaml")) for _, p in changes)

    if plugin_event and plugin_loader is not None:
        app_logger.info("V11 hot-reload: plugin.toml change detected")
        await plugin_loader.discover_and_load()

    if (route_event or pipeline_event) and route_loader is not None:
        app_logger.info(
            "V11 hot-reload: %s change detected — reloading routes",
            "route.toml" if route_event else "*.dsl.yaml",
        )
        await route_loader.unload_all()
        await route_loader.discover_and_load()


async def _start_dsl_yaml_watcher(app: FastAPI) -> None:
    """W25.1 — поднимает ``DSLYamlWatcher`` под флагом dsl.hot_reload_enabled.

    Watcher отслеживает ``dsl_routes/`` и атомарно перезагружает Pipeline'ы
    при изменении файлов. На dev_light/тестах флаг по умолчанию выключен —
    startup продолжается без watcher'а.
    """
    from src.backend.core.config.settings import settings as app_settings

    if not app_settings.dsl.hot_reload_enabled:
        app_logger.info("DSL hot-reload disabled (DSL_HOT_RELOAD_ENABLED=false)")
        return

    try:
        from src.backend.dsl.commands.registry import route_registry
        from src.backend.dsl.yaml_watcher import DSLYamlWatcher

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
    from src.backend.dsl.commands.setup import register_action_handlers
    from src.backend.dsl.routes import register_dsl_routes
    from src.backend.plugins.composition.service_setup import register_all_services
    from src.backend.plugins.composition.setup_infra import ending, starting

    app_logger.info("Запуск приложения...")
    startup_completed = False

    # Sprint 1 V16 (R-V15-11): инициализация TaskRegistry singleton —
    # все asyncio.create_task в проекте проходят через него для
    # graceful shutdown и correlation_id propagation. Выносится ДО
    # try, чтобы finally-блок мог корректно вызвать shutdown_all даже
    # при падении в startup.
    task_registry = get_task_registry()
    app.state.task_registry = task_registry

    try:
        from src.backend.plugins.composition.di import register_app_state

        # Wave A: Sentry init выполняется в самом начале lifespan, чтобы
        # последующие падения регистрации сервисов попадали в error tracking.
        # Без SENTRY_DSN init возвращает False и не блокирует старт.
        try:
            from src.backend.infrastructure.observability.sentry_init import init_sentry

            init_sentry()
        except Exception as sentry_exc:  # noqa: BLE001
            app_logger.warning(
                "Sentry init skipped: %s (приложение продолжит без error tracking)",
                sentry_exc,
            )

        # Wave 2.5: инициализация LogSink-стека (router + sinks по профилю)
        # должна произойти ДО регистрации сервисов, чтобы их startup-логи
        # уже доезжали до sink-ов (Console JSON / Disk Rotating / Graylog).
        # Падение инициализации не должно блокировать старт — приложение
        # продолжит работать с legacy stdlib-логированием.
        try:
            from src.backend.infrastructure.logging import init_log_sinks

            init_log_sinks()
        except Exception as log_exc:  # noqa: BLE001
            app_logger.warning(
                "LogSink router init skipped: %s (приложение продолжит на stdlib-логах)",
                log_exc,
            )

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

        # Wave 4-tail: PluginLoader bootstrap (in-tree + entry_points).
        # in-tree плагины из plugins/<dir>/plugin.yaml загружаются явно;
        # entry_points плагины — через importlib.metadata.entry_points.
        # Падения отдельных плагинов не блокируют startup.
        try:
            from pathlib import Path

            from src.backend.services.plugins import get_plugin_loader

            loader = get_plugin_loader()
            plugins_dir = Path("plugins")
            if plugins_dir.is_dir():
                for entry in plugins_dir.iterdir():
                    if not entry.is_dir():
                        continue
                    if (entry / "plugin.yaml").is_file():
                        try:
                            await loader.load_from_path(entry)
                        except Exception as plugin_exc:  # noqa: BLE001
                            app_logger.warning(
                                "In-tree plugin %s skipped: %s", entry.name, plugin_exc
                            )
            try:
                await loader.discover_and_load()
            except Exception as ep_exc:  # noqa: BLE001
                app_logger.warning("entry_points plugin discovery skipped: %s", ep_exc)
            app.state.plugin_loader = loader
        except Exception as exc:  # noqa: BLE001
            app_logger.warning("Plugin loader bootstrap skipped: %s", exc)

        # R1.fin (V11): bootstrap PluginLoaderV11 + RouteLoader под feature-flag.
        # Default OFF — wave 4.4 PluginLoader продолжает работать как раньше.
        await _bootstrap_v11_plugin_loader(app)
        await _bootstrap_v11_route_loader(app)
        await _start_v11_hot_reload(app)

        try:
            from src.backend.workflows.outbox_worker import start_outbox_worker

            start_outbox_worker(interval_seconds=5, batch_size=100)
        except Exception as exc:  # noqa: BLE001
            # Outbox-worker не критичен для базовой работоспособности
            # (например, dev_light без RabbitMQ) — startup продолжается.
            app_logger.warning("Outbox worker registration skipped: %s", exc)

        startup_completed = True
        app.state.infrastructure_ready = True

        from src.backend.dsl.commands.registry import action_handler_registry
        from src.backend.dsl.registry import route_registry

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
            from src.backend.workflows.outbox_worker import stop_outbox_worker

            await stop_outbox_worker()
        except Exception as worker_exc:  # noqa: BLE001
            app_logger.warning("Ошибка остановки outbox worker: %s", worker_exc)

        # R1.fin (V11): shutdown V11-loader'ов в обратном порядке
        # (route → plugin) ДО Wave 4 PluginLoader, чтобы их on_shutdown
        # успел отработать до закрытия общих ресурсов.
        await _shutdown_v11_loaders(app)

        # Wave 4-tail: graceful plugin shutdown — каждому плагину
        # даётся on_shutdown() до общего ending().
        plugin_loader = getattr(app.state, "plugin_loader", None)
        if plugin_loader is not None:
            try:
                await plugin_loader.shutdown_all()
            except Exception as plugin_exc:  # noqa: BLE001
                app_logger.warning("Plugin shutdown error: %s", plugin_exc)

        try:
            await ending()
        except Exception as shutdown_exc:
            app_logger.error(
                "Ошибка при завершении работы приложения: %s",
                str(shutdown_exc),
                exc_info=True,
            )

        app_logger.info("Приложение остановлено")

        # Wave 2.5: финальный flush + close всех LogSink-ов. Делается
        # после ``ending()`` и финального лога, чтобы зафиксировать в
        # sink-ах все события штатной остановки.
        try:
            from src.backend.infrastructure.logging import shutdown_log_sinks

            await shutdown_log_sinks()
        except Exception as sink_exc:  # noqa: BLE001
            app_logger.warning("LogSink shutdown error: %s", sink_exc)

        # Sprint 1 V16: pyrate_limiter Leaker shutdown-hook.
        # TODO V15.1 Sprint 1 Single Entry: вынести в core/resilience/_pyrate_compat.
        # Singleton Limiter из get_default_limiter() запускает фоновую
        # `_leaker.aio_leak_task`, которая течёт без явной остановки.
        try:
            import asyncio as _asyncio

            from src.backend.entrypoints.dependencies.rate_limit import (
                get_default_limiter,
            )

            limiter = get_default_limiter()
            leak_task = getattr(
                getattr(limiter, "_leaker", None), "aio_leak_task", None
            )
            if leak_task is not None and not leak_task.done():
                leak_task.cancel()
                try:
                    await leak_task
                except _asyncio.CancelledError:  # noqa: S110
                    pass
                except Exception as leak_done_exc:  # noqa: BLE001
                    app_logger.debug(
                        "pyrate Leaker join error: %s", leak_done_exc
                    )
        except Exception as leaker_exc:  # noqa: BLE001
            app_logger.warning("pyrate Leaker shutdown skipped: %s", leaker_exc)

        # Sprint 1 V16 (R-V15-11): graceful cancel всех зарегистрированных
        # фоновых задач. Делается ПОСЛЕ ending()/log shutdown, чтобы тех
        # задачи, которые ещё могли логировать остановку, успели завершиться.
        try:
            await task_registry.shutdown_all(timeout=10)
        except Exception as tr_exc:  # noqa: BLE001
            app_logger.warning("TaskRegistry shutdown error: %s", tr_exc)
