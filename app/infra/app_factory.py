import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from sqladmin import Admin
from starlette_exporter import PrometheusMiddleware, handle_metrics

from app.api.v1.routers import get_v1_routers
from app.config.settings import settings
from app.infra.db.database import db_initializer
from app.infra.logger import graylog_handler
from app.infra.queue import queue_client
from app.infra.redis import redis_client
from app.infra.smtp import smtp_client
from app.infra.storage import s3_client
from app.infra.stream_manager import stream_client
from app.services.infra_services.events import event_service
from app.services.infra_services.kafka import queue_service
from app.services.infra_services.queue_handlers import process_order
from app.utils.admins.files import FileAdmin, OrderFileAdmin
from app.utils.admins.orderkinds import OrderKindAdmin
from app.utils.admins.orders import OrderAdmin
from app.utils.admins.users import UserAdmin
from app.utils.decorators.limiting import _init_limiter
from app.utils.logging_service import app_logger
from app.utils.middlewares import (
    APIKeyMiddleware,
    InnerRequestLoggingMiddleware,
    RequestIDMiddleware,
    SecurityHeadersMiddleware,
    TimeoutMiddleware,
)
from app.utils.utils import utilities


__all__ = ("create_app",)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Контекстный менеджер для управления жизненным циклом приложения.

    Запускает планировщик задач и устанавливает лимиты запросов.
    Останавливает планировщик при завершении работы приложения.
    """
    original_env = dict(os.environ)

    load_dotenv()

    app_logger.info("Запуск приложения...")

    try:
        # Инициализация подключения к Graylog
        graylog_handler.connect()

        # Инициализация пула подключений Redis
        await redis_client.ensure_connected()

        # Инициализация пула подключений БД
        await db_initializer.initialize_async_pool()

        # Инициализация подключения к хранилищу файлов
        await s3_client.connect()

        # Инициализация подключения к SMTP-серверу
        await smtp_client.initialize_pool()

        # Инициализация событийной шины
        await event_service.register_handlers()
        await stream_client.start_consumer()

        # Инициализация клиента Kafka
        # await queue_client.initialize()
        # await queue_client.create_topics(["required_topics"])
        # await queue_service.start_message_consumption()
        # queue_service.register_handler("orders", process_order)

        # Инициализация лимитера запросов
        await _init_limiter()

        yield
    except Exception:
        app_logger.error("Error by starting", exc_info=True)
    finally:
        app_logger.info("Завершение работы приложения...")

        await stream_client.stop_consumer()
        await db_initializer.close()
        await s3_client.close()
        await smtp_client.close_pool()
        # await queue_service.stop_message_consumption()
        # await queue_client.close()
        await redis_client.close()
        graylog_handler.close()

        for key in os.environ:
            if key not in original_env:
                del os.environ[key]


def create_app() -> FastAPI:
    """
    Фабрика для создания и настройки экземпляра FastAPI приложения.

    Возвращает:
        FastAPI: Настроенное приложение FastAPI.
    """
    app = FastAPI(
        lifespan=lifespan,
        title="Расширенные инструменты GreenData",
        description="Это FastAPI приложение для управления заказами, файлами и пользователями.",
        version="1.0.0",
        debug=settings.app.debug_mode,
    )

    # Подключение Prometheus для сбора метрик
    instrumentator = Instrumentator()
    instrumentator.instrument(app).expose(app)

    # Middleware
    # app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(APIKeyMiddleware)
    app.add_middleware(TimeoutMiddleware)
    app.add_middleware(
        InnerRequestLoggingMiddleware, log_body=True, max_body_size=4096
    )
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=settings.auth.allowed_hosts
    )
    app.add_middleware(PrometheusMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """
        Глобальный обработчик исключений для всего приложения.
        Обрабатывает как стандартные, так и кастомные исключения.
        """
        # Обработка кастомных исключений с атрибутами status_code и message
        if hasattr(exc, "status_code") and hasattr(exc, "message"):
            return JSONResponse(
                status_code=exc.status_code,
                content=str(exc),
            )

        # Общая обработка всех остальных исключений
        return JSONResponse(
            status_code=500,
            content=str(exc),
        )

    # Использование роутера для API v1
    app.include_router(get_v1_routers(), prefix="/api/v1")

    # Подключение SQLAdmin для административной панели
    admin = Admin(app, db_initializer.async_engine)
    admin.add_view(UserAdmin)
    admin.add_view(OrderAdmin)
    admin.add_view(OrderKindAdmin)
    admin.add_view(OrderFileAdmin)
    admin.add_view(FileAdmin)

    # Эндпоинт для метрик Prometheus
    @app.get(
        "/metrics", summary="metrics", operation_id="metrics", tags=["Метрики"]
    )
    async def metrics(request: Request):
        return handle_metrics(request)

    # Корневой эндпоинт
    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def root():
        """
        Корневой эндпоинт, возвращающий HTML-страницу с приветствием и ссылками на сервисы.

        Возвращает:
            HTMLResponse: HTML-страница с описанием и ссылками.
        """
        log_url = await utilities.ensure_url_protocol(
            f"{settings.logging.host}:{settings.logging.port}"
        )
        fs_url = await utilities.ensure_url_protocol(
            settings.storage.interface_endpoint
        )
        flower_url = await utilities.ensure_url_protocol(
            settings.celery.flower_url
        )

        return f"""
        <!DOCTYPE html>
        <html lang="ru">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Добро пожаловать!</title>
            <style>
                body {{
                    font-family: 'Arial', sans-serif;
                    margin: 0;
                    padding: 0;
                    height: 100vh;
                    background: linear-gradient(to bottom right, #e0f7e0 50%, #ffffff 50%);
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    position: relative;
                    overflow: hidden;
                }}
                body::before {{
                    content: '';
                    position: absolute;
                    top: 0;
                    left: 0;
                    width: 100%;
                    height: 100%;
                    background:
                        radial-gradient(circle at 20% 20%, rgba(46, 125, 50, 0.1) 10%, transparent 10.5%),
                        radial-gradient(circle at 80% 20%, rgba(46, 125, 50, 0.1) 10%, transparent 10.5%),
                        radial-gradient(circle at 20% 80%, rgba(46, 125, 50, 0.1) 10%, transparent 10.5%),
                        radial-gradient(circle at 80% 80%, rgba(46, 125, 50, 0.1) 10%, transparent 10.5%);
                    z-index: 1;
                }}
                body::after {{
                    content: '';
                    position: absolute;
                    top: 0;
                    left: 0;
                    width: 100%;
                    height: 100%;
                    background:
                        radial-gradient(circle at 30% 30%, rgba(0, 123, 255, 0.1) 15%, transparent 15.5%),
                        radial-gradient(circle at 70% 30%, rgba(0, 123, 255, 0.1) 15%, transparent 15.5%),
                        radial-gradient(circle at 30% 70%, rgba(0, 123, 255, 0.1) 15%, transparent 15.5%),
                        radial-gradient(circle at 70% 70%, rgba(0, 123, 255, 0.1) 15%, transparent 15.5%);
                    z-index: 1;
                }}
                .container {{
                    text-align: center;
                    background-color: rgba(255, 255, 255, 0.9);
                    padding: 3rem;
                    border-radius: 20px;
                    box-shadow: 0 12px 24px rgba(0, 0, 0, 0.3);
                    max-width: 700px;
                    width: 90%;
                    border: 2px solid #2e7d32;
                    position: relative;
                    z-index: 2;
                }}
                h1 {{
                    font-size: 3rem;
                    margin-bottom: 1.5rem;
                    color: #2e7d32;
                    text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.2);
                }}
                p {{
                    font-size: 1.3rem;
                    margin-bottom: 2rem;
                    color: #333;
                    line-height: 1.6;
                }}
                .highlight {{
                    font-weight: bold;
                    color: #2e7d32;
                    text-shadow: 1px 1px 2px rgba(0, 0, 0, 0.1);
                }}
                a {{
                    color: #007bff;
                    text-decoration: none;
                    font-weight: bold;
                    border-bottom: 2px solid #007bff;
                    transition: all 0.3s ease;
                }}
                a:hover {{
                    color: #0056b3;
                    border-bottom-color: #0056b3;
                }}
                .admin-link {{
                    display: inline-block;
                    margin-top: 1.5rem;
                    padding: 0.75rem 1.5rem;
                    background-color: #2e7d32;
                    color: white;
                    border-radius: 8px;
                    text-decoration: none;
                    font-weight: bold;
                    transition: background-color 0.3s ease;
                }}
                .admin-link:hover {{
                    background-color: #1b5e20;
                }}
                .service-links {{
                    margin-top: 2rem;
                }}
                .service-links a {{
                    display: block;
                    margin: 0.5rem 0;
                    color: #2e7d32;
                    text-decoration: none;
                    font-weight: bold;
                }}
                .service-links a:hover {{
                    color: #1b5e20;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Расширенные инструменты GreenData</h1>
                <p>
                    Добро пожаловать в <span class="highlight">инновационное решение</span> для управления заказами, файлами и пользователями.
                    Наше приложение сочетает в себе <span class="highlight">удобство</span>, <span class="highlight">надежность</span> и <span class="highlight">высокую производительность</span>.
                </p>
                <p>
                    Для начала работы перейдите в <a href="/docs" target="_blank">документацию API</a>.
                </p>
                <a href="/admin" class="admin-link" target="_blank">Перейти в административную панель</a>
                <div class="service-links">
                    <h2>Технические интерфейсы</h2>
                    <a href="{log_url}" target="_blank">Хранилище логов</a>
                    <a href="{fs_url}" target="_blank">Файловое хранилище</a>
                    <a href="{flower_url}" target="_blank">Мониторинг задач</a>
                </div>
            </div>
        </body>
        </html>
        """

    return app
