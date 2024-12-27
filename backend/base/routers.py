from fastapi import APIRouter, Header
from fastapi.responses import PlainTextResponse
from fastapi_utils.cbv import cbv

from backend.core.settings import settings


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
