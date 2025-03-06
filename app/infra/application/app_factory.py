from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.api.v1.routers import get_v1_routers
from app.config.settings import settings
from app.infra.application.index import root_page
from app.infra.application.lifecycle import lifespan
from app.infra.application.monitoring import setup_monitoring
from app.infra.application.telemetry import setup_tracing
from app.infra.clients.stream import stream_client
from app.utils.admins.setup_admin import setup_admin
from app.utils.middlewares.setup_middlewares import setup_middlewares


__all__ = ("create_app",)


def create_app() -> FastAPI:
    """
    Фабрика для создания и конфигурации экземпляра приложения FastAPI.

    Выполняет:
    - Инициализацию основных компонентов приложения
    - Настройку middleware и инструментов наблюдения
    - Подключение маршрутизаторов API
    - Конфигурацию административного интерфейса
    - Настройку корневого эндпоинта

    Возвращает:
        FastAPI: Полностью сконфигурированный экземпляр приложения

    Исключения:
        RuntimeError: Возникает при ошибках конфигурации компонентов
        ImportError: При проблемах с импортом модулей
        ValueError: Некорректные настройки приложения

    Пример использования:
        app = create_app()
        uvicorn.run(app)
    """
    # Инициализация базового приложения
    app = FastAPI(
        lifespan=lifespan,
        version=settings.app.version,
        debug=settings.app.debug_mode,
        docs_url="/docs" if settings.app.enable_swagger else None,
        redoc_url="/redoc" if settings.app.enable_redoc else None,
    )

    try:
        # Настройка системных компонентов
        _configure_application_components(app)

        # Подключение бизнес-логики
        _configure_business_routers(app)

        # Настройка корневого эндпоинта
        _configure_root_endpoint(app)
    except Exception as exc:
        error_msg = f"Ошибка конфигурации приложения: {str(exc)}"
        raise RuntimeError(error_msg) from exc

    return app


def _configure_application_components(app: FastAPI) -> None:
    """Настройка системных компонентов приложения"""
    # Middleware для обработки запросов
    setup_middlewares(app=app)

    # Настройка распределенной трассировки
    if settings.app.telemetry_enabled:
        setup_tracing(app=app)

    # Подключение административного интерфейса
    if settings.app.admin_enabled:
        setup_admin(app=app)

    # Настройка системы мониторинга
    if settings.app.monitoring_enabled:
        setup_monitoring(app=app)


def _configure_business_routers(app: FastAPI) -> None:
    """Подключение бизнес-маршрутизаторов"""
    # Основное API приложения
    app.include_router(get_v1_routers(), prefix="/api/v1")

    # Интеграция с системами потоковой обработки
    app.include_router(
        stream_client.redis_router,
        prefix="/stream/redis",
        tags=["Redis Streams"],
    )

    app.include_router(
        stream_client.rabbit_router, prefix="/stream/rabbit", tags=["RabbitMQ"]
    )


def _configure_root_endpoint(app: FastAPI) -> None:
    """Конфигурация корневого эндпоинта"""

    @app.get("/", response_class=HTMLResponse, name="Корневой эндпоинт")
    async def root_endpoint():
        """
        Основная входная точка приложения

        Возвращает:
            HTMLResponse: Интерактивную стартовую страницу с:
            - Приветственным сообщением
            - Ссылками на документацию
            - Доступными сервисами
            - Административными интерфейсами
        """
        return await root_page()
