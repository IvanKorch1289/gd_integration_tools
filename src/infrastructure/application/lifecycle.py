from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.infrastructure.external_apis.logging_service import app_logger

__all__ = ("lifespan",)


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
        register_all_services()
        register_action_handlers()
        register_dsl_routes()
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
