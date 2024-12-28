import json

from fastapi import APIRouter, Header, Response
from fastapi.responses import PlainTextResponse
from fastapi_utils.cbv import cbv

from backend.core.settings import settings
from backend.core.utils import utilities


__all__ = ("router",)


router = APIRouter()


@cbv(router)
class TechBV:
    """CBV-класс для переадресаций на интерфейсы технических приложений."""

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
        "/healthcheck",
        summary="healthcheck",
        operation_id="healthcheck",
    )
    async def healthcheck(self):
        db_check = await utilities.health_check_database()
        redis_check = await utilities.health_check_redis()
        s3_check = await utilities.health_check_s3()
        graylog_check = await utilities.health_check_graylog()

        response_data = {
            "db": db_check,
            "redis": redis_check,
            "s3": s3_check,
            "graylog": graylog_check,
        }

        if all(response_data.values()):
            status_code = 200
            message = "All systems are operational."
        else:
            status_code = 500
            message = "One or more components are not functioning properly."

        response_body = {"message": message, "details": response_data}

        return Response(
            content=json.dumps(response_body),
            media_type="application/json",
            status_code=status_code,
        )
