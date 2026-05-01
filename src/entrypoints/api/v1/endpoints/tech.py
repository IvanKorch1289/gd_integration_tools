"""Tech-эндпоинты: HTML-редиректы на инфраструктурные UI + healthchecks.

W26.5: маршруты регистрируются декларативно — ActionSpec для healthcheck
и `add_api_route` для HTML-редиректов / multipart upload (последние не
вписываются в ActionSpec из-за нестандартного response_class и
``UploadFile``). Прямых ``@router.get/.post`` нет.
"""

from typing import Any

from fastapi import APIRouter, Depends, File, Header, Query, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse

from src.core.config.settings import settings
from src.core.di.providers import get_model_enum_provider
from src.core.enums.invocation import BrokerKind
from src.entrypoints.api.generator.actions import ActionRouterBuilder, ActionSpec
from src.entrypoints.api.generator.invocation import (
    EventPublishSpec,
    InvocationSpec,
    default_payload_factory,
)
from src.schemas.base import EmailSchema
from src.services.core.tech import get_tech_service


def get_model_enum() -> Any:
    """Wave 6.5a: thin-wrapper над DI provider.

    FastAPI ``Depends(get_model_enum)`` ожидает callable с правильной
    сигнатурой — сохраняем имя для совместимости с старыми вызовами.
    """
    factory = get_model_enum_provider()
    return factory()


__all__ = ("router",)


router = APIRouter()
builder = ActionRouterBuilder(router)


# --- HTML redirects (link-getters; нестандартный response_class) -----------


def _html_redirect_factory(method_name: str):
    """Возвращает endpoint-функцию, отдающую HTML-ссылку из tech-сервиса.

    Использование ``add_api_route`` вместо ``@router.get`` соответствует
    DoD W26.5: маршрутный декоратор отсутствует, регистрация — явная.
    """

    async def endpoint() -> str:
        method = getattr(get_tech_service(), method_name)
        return await method()

    endpoint.__name__ = method_name
    return endpoint


_HTML_LINKS: tuple[tuple[str, str, str], ...] = (
    ("/log-storage", "get_log_storage_link", "Ссылка на хранилище логов"),
    ("/file-storage", "get_file_storage_link", "Ссылка на файловое хранилище"),
    ("/queue-monitor", "get_queue_monitor_link", "Ссылка на мониторинг очередей"),
    ("/langfuse", "get_langfuse_link", "Ссылка на LangFuse Dashboard"),
    ("/langgraph", "get_langgraph_link", "Ссылка на LangGraph Studio"),
)
for path, method_name, summary in _HTML_LINKS:
    router.add_api_route(
        path=path,
        endpoint=_html_redirect_factory(method_name),
        methods=["GET"],
        response_class=HTMLResponse,
        summary=summary,
        name=method_name,
    )


# --- Excel mass-create upload (multipart/form-data) ------------------------


async def _upload_excel(
    file: UploadFile = File(...),
    table_name: str = Query(..., description="Название таблицы для загрузки данных."),
    model_enum: Any = Depends(get_model_enum),
    x_api_key: str = Header(...),
) -> Any:
    """Массовое создание объектов по Excel-файлу.

    UploadFile + Depends несовместимы с ActionSpec-генерацией сигнатуры,
    поэтому endpoint регистрируется через ``add_api_route``.
    """
    service = get_tech_service()
    content = await file.read()
    try:
        return await service.upload_excel_for_mass_create(
            file_bytes=content, table_name=table_name, model_enum=model_enum
        )
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"error": str(exc)})


router.add_api_route(
    path="/upload-excel-for-mass-create",
    endpoint=_upload_excel,
    methods=["POST"],
    status_code=status.HTTP_200_OK,
    summary="Загрузить Excel-файл для массового создания объектов",
    name="upload_excel_for_mass_create",
)


# --- Action-bus healthchecks + send-email ----------------------------------


builder.add_actions(
    [
        ActionSpec(
            name="healthcheck_database",
            method="GET",
            path="/healthcheck-database",
            summary="Проверить состояние базы данных",
            service_getter=get_tech_service,
            service_method="check_database",
        ),
        ActionSpec(
            name="healthcheck_redis",
            method="GET",
            path="/healthcheck-redis",
            summary="Проверить состояние Redis",
            service_getter=get_tech_service,
            service_method="check_redis",
        ),
        ActionSpec(
            name="healthcheck_s3",
            method="GET",
            path="/healthcheck-s3",
            summary="Проверить состояние S3",
            service_getter=get_tech_service,
            service_method="check_s3",
        ),
        ActionSpec(
            name="healthcheck_s3_bucket",
            method="GET",
            path="/healthcheck-s3-bucket",
            summary="Проверить наличие бакета в S3",
            service_getter=get_tech_service,
            service_method="check_s3_bucket",
        ),
        ActionSpec(
            name="healthcheck_graylog",
            method="GET",
            path="/healthcheck-graylog",
            summary="Проверить состояние Graylog",
            service_getter=get_tech_service,
            service_method="check_graylog",
        ),
        ActionSpec(
            name="healthcheck_smtp",
            method="GET",
            path="/healthcheck-smtp",
            summary="Проверить состояние SMTP-сервера",
            service_getter=get_tech_service,
            service_method="check_smtp",
        ),
        ActionSpec(
            name="healthcheck_rabbitmq",
            method="GET",
            path="/healthcheck-rabbitmq",
            summary="Проверить состояние RabbitMQ",
            service_getter=get_tech_service,
            service_method="check_rabbitmq",
        ),
        ActionSpec(
            name="healthcheck_all_services",
            method="GET",
            path="/healthcheck-all-services",
            summary="Проверить состояние всех сервисов",
            service_getter=get_tech_service,
            service_method="check_all_services",
        ),
        ActionSpec(
            name="get_all_custom_tables",
            method="GET",
            path="/get-all-custom-tables",
            summary="Получить названия всех таблиц",
            service_getter=get_tech_service,
            service_method="get_all_custom_tables",
            dependencies=[Depends(get_model_enum)],
        ),
        ActionSpec(
            name="send_email",
            method="POST",
            path="/send-email",
            summary="Отправить тестовое email",
            description="Публикует событие отправки email в Redis-стрим.",
            service_getter=get_tech_service,
            # Для event-only вызовов сервис-метод может быть пустышкой,
            # но мы укажем любой метод; реальная публикация произойдёт
            # через invocation.event.
            service_method="get_log_storage_link",
            body_model=EmailSchema,
            invocation=InvocationSpec(
                event=EventPublishSpec(
                    action="tech.send_email",
                    broker=BrokerKind.redis,
                    destination=settings.redis.get_stream_name("email"),
                    payload_factory=default_payload_factory,
                )
            ),
        ),
    ]
)
