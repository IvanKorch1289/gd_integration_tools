from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from src.backend.core.config.settings import settings
from src.backend.core.logging import get_logger
from src.backend.entrypoints.api.v1.routers import get_v1_routers
from src.backend.entrypoints.graphql.schema import graphql_router
from src.backend.entrypoints.grpc.proto_viewer import proto_viewer_router
from src.backend.entrypoints.middlewares.setup_middlewares import setup_middlewares
from src.backend.entrypoints.soap.soap_handler import soap_router
from src.backend.entrypoints.sse.handler import sse_router
from src.backend.entrypoints.webhook.handler import webhook_router
from src.backend.entrypoints.webhook.sources_router import (
    sources_router as webhook_sources_router,
)
from src.backend.entrypoints.websocket.ws_handler import ws_router
from src.backend.entrypoints.websocket.ws_invocations import ws_invocations_router
from src.backend.infrastructure.application.index import root_page
from src.backend.infrastructure.application.monitoring import setup_monitoring
from src.backend.infrastructure.application.telemetry import setup_tracing
from src.backend.infrastructure.clients.messaging.stream import get_stream_client
from src.backend.plugins.composition.lifecycle import lifespan
from src.backend.utilities.admin_panel.setup_admin import setup_admin

__all__ = ("create_app",)


def create_app() -> FastAPI:
    """Фабрика для создания и конфигурации экземпляра приложения FastAPI.

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
        error_msg = f"Ошибка конфигурации приложения: {exc!s}"
        raise RuntimeError(error_msg) from exc

    return app


def _configure_application_components(app: FastAPI) -> None:
    """Настройка системных компонентов приложения."""
    # Middleware для обработки запросов
    setup_middlewares(app=app)

    # D-AUDIT-20807 fix (cycle 216): mount MCP HTTP transport ВНУТРИ
    # create_app() (а не module-level в main.py). Cycle 215 investigation
    # обнаружил что granian/uvicorn импортирует ТОЛЬКО атрибут `app`
    # (через "src.backend.main:app"), НЕ module body — поэтому
    # module-level _mount_mcp_http() вызов НЕ выполняется в runtime.
    # Решение: mount ВНУТРИ create_app() (которая IS called при import).
    _mount_mcp_http(app)

    # Настройка распределенной трассировки. OTLP-коллектор может быть
    # недоступен в dev/ci — ловим исключения чтобы не ломать старт приложения.
    if settings.app.telemetry_enabled:
        try:
            setup_tracing(app=app)
        except Exception as exc:
            get_logger("app_factory").warning(
                "OpenTelemetry setup failed: %s (приложение продолжит работу без трейсинга)",
                exc,
            )

    # Подключение административного интерфейса
    if settings.app.admin_enabled:
        setup_admin(app=app)

    # Настройка системы мониторинга
    if settings.app.monitoring_enabled:
        setup_monitoring(app=app)


def _mount_mcp_http(app: FastAPI) -> None:
    """Mount FastMCP HTTP transport в FastAPI app (cycle 209-216, D-AUDIT-20803+).

    Вызывается из ``_configure_application_components()`` (НЕ module-level
    в main.py) потому что granian/uvicorn импортирует ТОЛЬКО атрибут
    ``app`` (через "src.backend.main:app"), НЕ module body — module-level
    вызовы НЕ выполняются в runtime (D-AUDIT-20807, cycle 216).

    Ponytail: 1 функция, 1 mount point. Skip если ``mcp_settings.http_enabled=False``.
    """
    try:
        from src.backend.core.config.ai_stack import mcp_settings
    except ImportError as exc:
        get_logger(__name__).warning(
            "MCP HTTP transport: mcp_settings import failed — mount skipped (%s: %s)",
            type(exc).__name__,
            exc,
        )
        return
    if not mcp_settings.http_enabled:
        return
    try:
        from src.backend.entrypoints.mcp.http_server import create_mcp_http_app

        mcp_asgi, mcp_inner_lifespan = create_mcp_http_app()
        app.mount(mcp_settings.bind_path, mcp_asgi)
        # D-AUDIT-20804 (cycle 210): disable redirect_slashes (см. main.py history).
        app.router.redirect_slashes = False

        # D-AUDIT-20805 (cycle 213): wire FastMCP lifespan (lifespan_context function).
        _existing_lifespan = app.router.lifespan

        @asynccontextmanager
        async def _combined_lifespan(app_arg):
            async with mcp_inner_lifespan(app_arg):
                async with _existing_lifespan(app_arg):
                    yield

        app.router.lifespan = _combined_lifespan

        get_logger(__name__).info(
            "MCP HTTP transport mounted at %s "
            "(redirect_slashes=False, lifespan=combined)",
            mcp_settings.bind_path,
        )
    except Exception as exc:
        get_logger(__name__).warning("MCP HTTP transport mount skipped: %s", exc)


def _configure_business_routers(app: FastAPI) -> None:
    """Подключение бизнес-маршрутизаторов."""
    from fastapi import APIRouter
    from fastapi.responses import RedirectResponse

    from src.backend.entrypoints.filewatcher.watcher_routes import watcher_router

    # S27 Wave 3: admin-react API bridge — редирект /api/admin/* → /api/v1/admin/*
    # admin-react вызывает /api/admin/<path>, но реальное API на /api/v1/admin/<path>
    # 303 See Other: семантически корректен для temporary redirect, POST→GET
    # избегает риска повторной отправки body (307 сохраняет метод)
    _admin_bridge_router = APIRouter()

    @_admin_bridge_router.api_route(
        "/api/admin/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    )
    async def admin_legacy_redirect(path: str):
        """Redirect legacy admin API paths to v1 admin API.

        Args:
            path: Legacy admin path.

        Returns:
            Redirect response to /api/v1/admin/{path}.

        """
        # Защита от open redirect: валидируем что path только относительный
        from urllib.parse import urlparse

        parsed = urlparse(f"/{path}")  # Префикс "/" для корректного парсинга
        if parsed.scheme or parsed.netloc:
            from fastapi import HTTPException

            raise HTTPException(
                status_code=400, detail="Invalid path: external URLs not allowed",
            )
        return RedirectResponse(url=f"/api/v1/admin/{path}", status_code=303)

    app.include_router(_admin_bridge_router)

    # NEW-3a fix (2026-08-14): ``/asyncapi`` (bare, без префикса v1)
    # включён в ``routes_without_api_key`` (``auth_required.py:54``),
    # но ни один router не mounted at root-level ``/asyncapi`` → 404.
    # Streamlit pages 65 + registry_tab ссылаются на ``/asyncapi``.
    # Решение: bridge-endpoint отдаёт AsyncAPI spec **напрямую** (не redirect),
    # чтобы избежать проблем с prefix-matching ``.json``/``.yaml`` суффиксов
    # в ``auth_required.is_public_path`` (см. ``middleware/auth_required.py:75-81``).
    _asyncapi_bridge_router = APIRouter()

    @_asyncapi_bridge_router.get("/asyncapi", include_in_schema=False)
    async def asyncapi_legacy_serve():
        """Сервит AsyncAPI 3.0 JSON spec по bare ``/asyncapi`` пути.

        Streaminglit pages и registry_tab ссылаются на ``/asyncapi`` как
        на public endpoint — отдаём spec напрямую, без HTTP-redirect.
        """
        from fastapi.responses import JSONResponse

        from src.backend.entrypoints.asyncapi import build_asyncapi_json

        return JSONResponse(content=build_asyncapi_json(), media_type="application/json")

    app.include_router(_asyncapi_bridge_router)

    # Основное API приложения
    app.include_router(get_v1_routers(), prefix="/api/v1")

    # Wave 1.2 (Roadmap V10): REST auto-loop. Регистрируем все
    # зарегистрированные action-handlers (через
    # ``action_handler_registry``), для которых ещё нет HTTP-роута,
    # как авто-эндпоинты на ``/api/v1/auto/<action>``. Идемпотентно —
    # повторный вызов не добавит дубликаты.
    _configure_auto_registered_actions(app)

    # Wave 1.4 (Roadmap V10): GraphQL auto-schema на ``/api/v1/graphql``.
    # Сосуществует с hand-written ``graphql_router`` на ``/graphql``,
    # покрывает Tier 1/2 actions, у которых ``"graphql"`` в transports.
    _configure_auto_graphql_schema(app)

    # Интеграция с системами потоковой обработки. На dev_light профиле
    # ``redis.enabled=false`` / ``queue.enabled=false`` делают
    # соответствующий FastStream router None — пропускаем.
    # Явные импорты subscriber-модулей: декораторы ``@router.subscriber(...)``
    # регистрируются при импорте, поэтому их нужно подгрузить ДО
    # ``app.include_router(redis_router/rabbit_router)``.
    stream_client = get_stream_client()
    if (
        stream_client.redis_router is not None
        or stream_client.rabbit_router is not None
    ):
        from src.backend.entrypoints.stream import (  # noqa: F401 — availability probe
            invoker_subscribers,
            subscribers,
        )

    if stream_client.redis_router is not None:
        app.include_router(
            stream_client.redis_router, prefix="/stream/redis", tags=["Redis Streams"],
        )
    if stream_client.rabbit_router is not None:
        app.include_router(
            stream_client.rabbit_router, prefix="/stream/rabbit", tags=["RabbitMQ"],
        )

    # Протокольные entrypoints
    app.include_router(proto_viewer_router)
    app.include_router(graphql_router)
    app.include_router(ws_router)
    app.include_router(ws_invocations_router)
    app.include_router(watcher_router, prefix="/api/v1")
    app.include_router(soap_router)
    app.include_router(sse_router)
    app.include_router(webhook_router)
    app.include_router(webhook_sources_router)

    # CDC
    from src.backend.entrypoints.cdc.cdc_routes import cdc_router

    app.include_router(cdc_router)

    # Express BotX (Wave 4.2)
    from src.backend.entrypoints.express import router as express_router

    app.include_router(express_router)


def _configure_auto_registered_actions(app: FastAPI) -> None:
    """Подключение авто-роутов для action-handlers без явного REST-маршрута.

    Wave 1.2: после регистрации основных бизнес-роутов сканируем
    ``ActionHandlerRegistry.list_actions()`` и для каждого action без
    соответствующего FastAPI-роута создаём sane-default endpoint на
    ``/api/v1/auto/<action>``.

    Чтобы реестр был наполнен на момент вызова, сначала идемпотентно
    вызываем ``register_action_handlers()`` (тот же путь использует
    ``manage.py`` для introspection). Если вызов упадёт из-за
    отсутствующих опциональных зависимостей (dev_light) — log + skip,
    стартап приложения не блокируем.
    """
    from src.backend.entrypoints.api.generator.auto_register import (
        auto_register_unrouted_actions,
    )

    try:
        from src.backend.dsl.commands.setup import register_action_handlers

        register_action_handlers()
    except Exception as exc:
        get_logger("app_factory").warning(
            "register_action_handlers пропущен: %s "
            "(action auto-loop пройдёт по уже существующим handler'ам)",
            exc,
        )

    try:
        added = auto_register_unrouted_actions(app)
    except Exception as exc:
        get_logger("app_factory").warning(
            "auto_register_unrouted_actions упал: %s — пропускаем", exc,
        )
        return

    if added:
        get_logger("app_factory").info(
            "Wave 1.2: авто-зарегистрировано %d REST-роутов для action-handlers", added,
        )


def _configure_auto_graphql_schema(app: FastAPI) -> None:
    """Подключить Strawberry auto-schema на ``/api/v1/graphql``.

    Wave 1.4 (Roadmap V10): динамически собираем Query/Mutation из
    ``ActionMetadata`` (transports содержит ``"graphql"``). Не ломает
    существующий ``graphql_router`` (``/graphql`` остаётся живым).
    Любые ошибки сборки логгируются и не блокируют старт приложения.
    """
    try:
        from src.backend.entrypoints.graphql.auto_schema import (
            auto_register_strawberry_schema,
        )

        auto_register_strawberry_schema(app, path="/api/v1/graphql")
    except Exception as exc:
        get_logger("app_factory").warning("Wave 1.4 auto-schema пропущена: %s", exc)


def _configure_root_endpoint(app: FastAPI) -> None:
    """Конфигурация корневого эндпоинта и health/ready-проб для Kubernetes.

    Эндпоинты ``/health`` (liveness) и ``/ready`` (readiness) вынесены на
    корневой уровень, чтобы k8s-пробы не зависели от роутинга ``/api/v1``.
    """

    @app.get("/", response_class=HTMLResponse, name="Корневой эндпоинт")
    async def root_endpoint():
        """Основная входная точка приложения.

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

    @app.get("/health/live", include_in_schema=False)
    async def liveness_alias():
        """Alias for /health (k8s livenessProbe convention)."""
        return await liveness()

    @app.get("/ready", name="Readiness probe", tags=["Health"])
    async def readiness():
        """Readiness probe: агрегированная проверка критичных компонентов.

        Возвращает 200 если все зарегистрированные компоненты healthy, 503 иначе.
        Использует :class:`HealthAggregator` с параллельным опросом и таймаутом.
        """
        from fastapi.responses import JSONResponse

        from src.backend.infrastructure.application.health_aggregator import (
            get_health_aggregator,
        )

        report = await get_health_aggregator().check_all()
        ok = report.get("status") == "ok"

    @app.get("/health/ready", include_in_schema=False)
    async def readiness_alias():
        """Alias for /ready (k8s readinessProbe convention)."""
        return await readiness()
        return JSONResponse(status_code=200 if ok else 503, content=report)
