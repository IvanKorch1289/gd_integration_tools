from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.infrastructure.external_apis.logging_service import app_logger

__all__ = ("lifespan",)


def _register_protocol_providers() -> None:
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

    # Notification channels — каждый канал отдельно через адаптер.
    try:
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
    except Exception as exc:  # noqa: BLE001
        app_logger.debug("Notifier registration skipped: %s", exc)

    # Prompt store (in-memory fallback, при наличии LangFuse — он приоритетен).
    try:
        from src.services.ai.prompt_registry import get_prompt_registry

        register_provider("prompt_store", "default", get_prompt_registry())
    except Exception as exc:  # noqa: BLE001
        app_logger.debug("Prompt store registration skipped: %s", exc)

    from src.core.providers_registry import list_providers

    app_logger.info("Protocol providers registered: %s", list_providers())


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Управляет жизненным циклом приложения FastAPI.
    """
    from src.dsl.commands.setup import register_action_handlers
    from src.dsl.routes import register_dsl_routes
    from src.infrastructure.application.service_setup import register_all_services
    from src.infrastructure.setup_infra import ending, starting

    app_logger.info("Запуск приложения...")
    startup_completed = False

    try:
        from src.infrastructure.application.di import register_app_state

        register_app_state(app)

        register_all_services()
        register_action_handlers()
        register_dsl_routes()
        _register_protocol_providers()
        _validate_cache_layers()
        await starting()

        from src.workflows.outbox_worker import start_outbox_worker

        start_outbox_worker(interval_seconds=5, batch_size=100)

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
