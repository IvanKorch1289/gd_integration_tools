from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from sqladmin import Admin
from starlette_exporter import PrometheusMiddleware, handle_metrics

from backend.api_skb import skb_router
from backend.base import tech_router
from backend.core.database import database
from backend.core.logging_config import app_logger
from backend.core.middlewares import (
    APIKeyMiddleware,
    LoggingMiddleware,
    TimeoutMiddleware,
)
from backend.core.scheduler import (
    scheduler_manager,
    send_request_for_checking_services,
)
from backend.core.settings import settings
from backend.files import (
    FileAdmin,
    OrderFileAdmin,
    file_router,
    storage_router,
)
from backend.order_kinds import OrderKindAdmin, kind_router
from backend.orders import OrderAdmin, order_router
from backend.users import UserAdmin, user_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    app_logger.info("Запуск приложения...")
    try:
        await scheduler_manager.add_task(
            send_request_for_checking_services, interval_seconds=3600
        )
        await scheduler_manager.start_scheduler()

        app_logger.info("Планировщик запущен...")

        yield
    except Exception as exc:
        app_logger.error(f"Ошибка инициализации планировщика: {str(exc)}")
    finally:
        await scheduler_manager.stop_scheduler()

        app_logger.info("Завершение работы приложения...")
        app_logger.info("Планировщик остановлен...")


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    app.debug = settings.app_debug

    # Подключение Prometheus для сбора метрик
    @app.get("/metrics", summary="metrics", operation_id="metrics", tags=["Метрики"])
    async def metrics(request: Request):
        return handle_metrics(request)

    instrumentator = Instrumentator()
    instrumentator.instrument(app).expose(app)

    # Подключение Middleware
    @app.middleware("http")
    async def logger_middleware(request: Request, call_next):
        return await LoggingMiddleware().__call__(request, call_next)

    @app.middleware("http")
    async def api_key_middleware(request: Request, call_next):
        return await APIKeyMiddleware().__call__(request, call_next)

    @app.middleware("http")
    async def timeout_middleware(request: Request, call_next):
        return await TimeoutMiddleware().__call__(request, call_next)

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.app_allowed_hosts)
    app.add_middleware(PrometheusMiddleware)

    # Подключение SQLAdmin
    admin = Admin(app, database.async_engine)
    admin.add_view(UserAdmin)
    admin.add_view(OrderAdmin)
    admin.add_view(OrderKindAdmin)
    admin.add_view(OrderFileAdmin)
    admin.add_view(FileAdmin)

    # Подключение роутеров
    app.include_router(
        kind_router, prefix="/kind", tags=["Работа со справочником видов запросов"]
    )
    app.include_router(
        storage_router, prefix="/storage", tags=["Работа с файлами в S3"]
    )
    app.include_router(file_router, prefix="/file", tags=["Работа с файлами в БД"])
    app.include_router(order_router, prefix="/order", tags=["Работа с запросами"])
    app.include_router(skb_router, prefix="/skb", tags=["Работа с API СКБ Техно"])
    app.include_router(
        storage_router, prefix="/storage", tags=["Работа с хранилищем файлов"]
    )
    app.include_router(user_router, prefix="/user", tags=["Работа с пользователями"])
    app.include_router(tech_router, prefix="/tech", tags=["Техническое"])

    return app
