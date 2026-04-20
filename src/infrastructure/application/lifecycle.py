from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.infrastructure.external_apis.logging_service import app_logger

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
    from app.core.providers_registry import register_provider

    # LLM провайдеры (работают если есть env-переменные с ключами).
    try:
        from app.services.ai.ai_providers import (
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

    # Export форматы — по одному инстансу сервиса на все форматы.
    try:
        from app.services.io.export_service import get_export_service
        register_provider("exporter", "default", get_export_service())
    except Exception as exc:  # noqa: BLE001
        app_logger.debug("Exporter registration skipped: %s", exc)

    # Agent memory (Redis-backed).
    try:
        from app.services.ai.agent_memory import get_agent_memory_service
        register_provider("memory", "redis", get_agent_memory_service())
    except Exception as exc:  # noqa: BLE001
        app_logger.debug("Memory backend registration skipped: %s", exc)

    # Notification hub — единый канал-диспетчер.
    try:
        from app.services.ops.notification_hub import get_notification_hub
        register_provider("notifier", "hub", get_notification_hub())
    except Exception as exc:  # noqa: BLE001
        app_logger.debug("Notifier registration skipped: %s", exc)

    # Prompt store (in-memory fallback, при наличии LangFuse — он приоритетен).
    try:
        from app.services.ai.prompt_registry import get_prompt_registry
        register_provider("prompt_store", "default", get_prompt_registry())
    except Exception as exc:  # noqa: BLE001
        app_logger.debug("Prompt store registration skipped: %s", exc)

    from app.core.providers_registry import list_providers
    app_logger.info("Protocol providers registered: %s", list_providers())


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Управляет жизненным циклом приложения FastAPI.
    """
    from app.core.service_setup import register_all_services
    from app.dsl.commands.setup import register_action_handlers
    from app.dsl.routes import register_dsl_routes
    from app.infrastructure.setup_infra import ending, starting

    app_logger.info("Запуск приложения...")
    startup_completed = False

    try:
        from app.core.di import register_app_state

        register_app_state(app)

        register_all_services()
        register_action_handlers()
        register_dsl_routes()
        _register_protocol_providers()
        await starting()

        startup_completed = True
        app.state.infrastructure_ready = True

        from app.dsl.commands.registry import action_handler_registry
        from app.dsl.registry import route_registry

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
            await ending()
        except Exception as shutdown_exc:
            app_logger.error(
                "Ошибка при завершении работы приложения: %s",
                str(shutdown_exc),
                exc_info=True,
            )

        app_logger.info("Приложение остановлено")
