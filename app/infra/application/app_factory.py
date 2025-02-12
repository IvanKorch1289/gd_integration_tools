from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.api.v1.routers import get_v1_routers
from app.config.settings import settings
from app.infra.application.handlers import setup_handlers
from app.infra.application.index import root_page
from app.infra.application.lifecycle import lifespan
from app.infra.application.monitoring import setup_monitoring
# from app.infra.application.telemetry import setup_tracing
from app.utils.admins.setup_admin import setup_admin
from app.utils.middlewares.setup_middlewares import setup_middlewares


__all__ = ("create_app",)


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
        version=settings.app.version,
        debug=settings.app.debug_mode,
    )

    # Middleware
    setup_middlewares(app=app)

    # Трассировка
    # setup_tracing(app=app)

    # Перехват исключений
    # setup_handlers(app=app)

    # Подключение SQLAdmin для административной панели
    setup_admin(app=app)

    # Метрики
    setup_monitoring(app=app)

    # Использование роутера для API v1
    app.include_router(get_v1_routers(), prefix="/api/v1")

    # Корневой эндпоинт
    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def root():
        """
        Корневой эндпоинт, возвращающий HTML-страницу с приветствием и ссылками на сервисы.

        Возвращает:
            HTMLResponse: HTML-страница с описанием и ссылками.
        """
        return await root_page()

    return app
