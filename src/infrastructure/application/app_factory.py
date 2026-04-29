from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from src.core.config.settings import settings
from src.entrypoints.api.v1.routers import get_v1_routers
from src.entrypoints.graphql.schema import graphql_router
from src.entrypoints.grpc.proto_viewer import proto_viewer_router
from src.entrypoints.middlewares.setup_middlewares import setup_middlewares
from src.entrypoints.soap.soap_handler import soap_router
from src.entrypoints.sse.handler import sse_router
from src.entrypoints.webhook.handler import webhook_router
from src.entrypoints.websocket.ws_handler import ws_router
from src.infrastructure.application.index import root_page
from src.infrastructure.application.lifecycle import lifespan
from src.infrastructure.application.monitoring import setup_monitoring
from src.infrastructure.application.telemetry import setup_tracing
from src.infrastructure.clients.messaging.stream import stream_client
from src.utilities.admin_panel.setup_admin import setup_admin

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

    # Настройка распределенной трассировки. OTLP-коллектор может быть
    # недоступен в dev/ci — ловим исключения чтобы не ломать старт приложения.
    if settings.app.telemetry_enabled:
        try:
            setup_tracing(app=app)
        except Exception as exc:  # noqa: BLE001
            import logging

            logging.getLogger("app_factory").warning(
                "OpenTelemetry setup failed: %s (приложение продолжит работу без трейсинга)",
                exc,
            )

    # Подключение административного интерфейса
    if settings.app.admin_enabled:
        setup_admin(app=app)

    # Настройка системы мониторинга
    if settings.app.monitoring_enabled:
        setup_monitoring(app=app)


def _configure_business_routers(app: FastAPI) -> None:
    """Подключение бизнес-маршрутизаторов"""
    from src.entrypoints.filewatcher.watcher_routes import watcher_router

    # Основное API приложения
    app.include_router(get_v1_routers(), prefix="/api/v1")

    # Интеграция с системами потоковой обработки. На dev_light профиле
    # ``redis.enabled=false`` / ``queue.enabled=false`` делают
    # соответствующий FastStream router None — пропускаем.
    if stream_client.redis_router is not None:
        app.include_router(
            stream_client.redis_router, prefix="/stream/redis", tags=["Redis Streams"]
        )
    if stream_client.rabbit_router is not None:
        app.include_router(
            stream_client.rabbit_router, prefix="/stream/rabbit", tags=["RabbitMQ"]
        )

    # Протокольные entrypoints
    app.include_router(proto_viewer_router)
    app.include_router(graphql_router)
    app.include_router(ws_router)
    app.include_router(watcher_router, prefix="/api/v1")
    app.include_router(soap_router)
    app.include_router(sse_router)
    app.include_router(webhook_router)

    # CDC
    from src.entrypoints.cdc.cdc_routes import cdc_router

    app.include_router(cdc_router)

    # Express BotX (Wave 4.2)
    from src.entrypoints.express import router as express_router

    app.include_router(express_router)


def _configure_root_endpoint(app: FastAPI) -> None:
    """Конфигурация корневого эндпоинта и health/ready-проб для Kubernetes.

    Эндпоинты ``/health`` (liveness) и ``/ready`` (readiness) вынесены на
    корневой уровень, чтобы k8s-пробы не зависели от роутинга ``/api/v1``.
    """

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

    @app.get("/health", name="Liveness probe", tags=["Health"])
    async def liveness():
        """Liveness probe: приложение работает, event loop отвечает."""
        return {"status": "alive", "version": settings.app.version}

    @app.get("/ready", name="Readiness probe", tags=["Health"])
    async def readiness():
        """Readiness probe: агрегированная проверка критичных компонентов.

        Возвращает 200 если все зарегистрированные компоненты healthy, 503 иначе.
        Использует :class:`HealthAggregator` с параллельным опросом и таймаутом.
        """
        from fastapi.responses import JSONResponse

        from src.infrastructure.application.health_aggregator import (
            get_health_aggregator,
        )

        report = await get_health_aggregator().check_all()
        ok = report.get("status") == "ok"
        return JSONResponse(status_code=200 if ok else 503, content=report)
