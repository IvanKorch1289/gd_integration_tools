from typing import Any

from fastapi import APIRouter, Depends, File, Header, Query, UploadFile
from fastapi.responses import HTMLResponse

from src.core.config.settings import settings
from src.core.enums.invocation import BrokerKind
from src.entrypoints.api.generator.actions import ActionRouterBuilder, ActionSpec
from src.entrypoints.api.generator.invocation import (
    EventPublishSpec,
    InvocationSpec,
    default_payload_factory,
)
from src.infrastructure.database.model_registry import get_model_enum
from src.schemas.base import EmailSchema
from src.services.core.tech import get_tech_service

__all__ = ("router",)


router = APIRouter()
builder = ActionRouterBuilder(router)


# 1. HTML-роуты обернем в обычные методы, так как ActionSpec
# по умолчанию возвращает JSONResponse.
@router.get(
    "/log-storage", response_class=HTMLResponse, summary="Ссылка на хранилище логов"
)
async def redirect_to_log_storage():
    return await get_tech_service().get_log_storage_link()


@router.get(
    "/file-storage", response_class=HTMLResponse, summary="Ссылка на файловое хранилище"
)
async def redirect_to_file_storage():
    return await get_tech_service().get_file_storage_link()


@router.get(
    "/queue-monitor",
    response_class=HTMLResponse,
    summary="Ссылка на мониторинг очередей",
)
async def redirect_to_queue_monitor():
    return await get_tech_service().get_queue_monitor_link()


@router.get(
    "/langfuse", response_class=HTMLResponse, summary="Ссылка на LangFuse Dashboard"
)
async def redirect_to_langfuse():
    return await get_tech_service().get_langfuse_link()


@router.get(
    "/langgraph", response_class=HTMLResponse, summary="Ссылка на LangGraph Studio"
)
async def redirect_to_langgraph():
    return await get_tech_service().get_langgraph_link()


# 2. Массовая загрузка из Excel (из-за UploadFile используем обычный роут)
@router.post(
    "/upload-excel-for-mass-create",
    summary="Загрузить Excel-файл для массового создания объектов",
)
async def upload_excel(
    file: UploadFile = File(...),
    table_name: str = Query(..., description="Название таблицы для загрузки данных"),
    model_enum: Any = Depends(get_model_enum),
    x_api_key: str = Header(...),
):
    service = get_tech_service()
    content = await file.read()

    try:
        results = await service.upload_excel_for_mass_create(
            file_bytes=content, table_name=table_name, model_enum=model_enum
        )
        return results
    except ValueError as e:
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=404, content={"error": str(e)})


# 3. Action Bus роуты для Healthchecks и отправки email
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
            # но мы укажем любой метод, реальная публикация произойдет через invocation.
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
