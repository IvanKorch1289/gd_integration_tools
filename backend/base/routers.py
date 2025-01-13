from fastapi import APIRouter, Header
from fastapi.responses import PlainTextResponse
from fastapi_utils.cbv import cbv

from backend.base.schemas import EmailSchema
from backend.base.service import BaseService
from backend.core.settings import settings
from backend.core.utils import utilities


__all__ = ("router",)


router = APIRouter()


@cbv(router)
class TechBV:
    """CBV-класс для переадресаций на интерфейсы технических приложений."""

    service = BaseService()

    @router.get(
        "/log-storage",
        summary="Получить ссылку на хранилище логов",
        operation_id="getLinkToLogStorage",
    )
    async def redirest_to_log_storage(self, x_api_key: str = Header(...)):
        return PlainTextResponse(
            f"{settings.logging_settings.log_host}:{settings.logging_settings.log_port}"
        )

    @router.get(
        "/file-storage",
        summary="Получить ссылку на файловое хранилище",
        operation_id="getLinkToFileStorage",
    )
    async def redirest_to_file_storage(self, x_api_key: str = Header(...)):
        return PlainTextResponse(f"{settings.storage_settings.fs_interfase_url}")

    @router.get(
        "/task-monitor",
        summary="Получить ссылку на интерфейс мониторинга фоновых задач",
        operation_id="getLinkToFlower",
    )
    async def redirest_to_task_monitor(self, x_api_key: str = Header(...)):
        return PlainTextResponse(settings.bts_settings.bts_interface_url)

    @router.get(
        "/healthcheck_database",
        summary="healthcheck_database",
        operation_id="healthcheck_database",
    )
    async def healthcheck_database(self):
        return await utilities.health_check_database()

    @router.get(
        "/healthcheck_redis",
        summary="healthcheck_redis",
        operation_id="healthcheck_redis",
    )
    async def healthcheck_redis(self):
        return await utilities.health_check_redis()

    @router.get(
        "/healthcheck_celery",
        summary="healthcheck_celery",
        operation_id="healthcheck_celery",
    )
    async def healthcheck_celery(self):
        return await utilities.health_check_celery()

    @router.get(
        "/healthcheck_s3",
        summary="healthcheck_s3",
        operation_id="healthcheck_s3",
    )
    async def healthcheck_s3(self):
        return await utilities.health_check_s3()

    @router.get(
        "/healthcheck_graylog",
        summary="healthcheck_graylog",
        operation_id="healthcheck_graylog",
    )
    async def healthcheck_graylog(self):
        return await utilities.health_check_graylog()

    @router.get(
        "/healthcheck_smtp",
        summary="healthcheck_smtp",
        operation_id="healthcheck_smtp",
    )
    async def healthcheck_smtp(self):
        return await utilities.health_check_smtp()

    @router.get(
        "/healthcheck_all_services",
        summary="healthcheck_all_services",
        operation_id="healthcheck_all_services",
    )
    async def healthcheck_all_services(self):
        return await utilities.health_check_all_services()

    @router.post(
        "/send_email",
        summary="send_email",
        operation_id="send_email",
    )
    async def send_email(self, schema: EmailSchema):
        return await utilities.send_email(
            to_email=schema.to_email, subject=schema.subject, message=schema.message
        )
