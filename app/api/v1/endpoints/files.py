import uuid

from fastapi import APIRouter, File, Header, Request, UploadFile, status
from fastapi_utils.cbv import cbv

from app.core import create_cbv_class
from app.core.dependencies import get_streaming_response
from app.core.errors import handle_routes_errors
from app.core.limiter import route_limiter
from app.core.storage import s3_bucket_service_factory
from app.schemas import (
    FileFilter,
    FileSchemaIn,
    FileSchemaOut,
    FileVersionSchemaOut,
)
from app.services.files import get_file_service


__all__ = (
    "router",
    "storage_router",
)


router = APIRouter()


FileCBV = create_cbv_class(
    router=router,
    schema_in=FileSchemaIn,
    schema_out=FileSchemaOut,
    version_schema_out=FileVersionSchemaOut,
    service=get_file_service(),
    filter_class=FileFilter,
)


storage_router = APIRouter()


@cbv(storage_router)
class StorageCBV:
    """
    CBV-класс для работы с файлами в S3.

    Предоставляет методы для загрузки, скачивания, удаления и получения ссылок на файлы.
    """

    service = s3_bucket_service_factory()

    @storage_router.post(
        "/upload_file",
        status_code=status.HTTP_201_CREATED,
        summary="Добавить файл в S3",
        operation_id="uploadFileStorageUploadFilePostUnique",
    )
    @route_limiter
    @handle_routes_errors
    async def upload_file(
        self,
        request: Request,
        file: UploadFile = File(...),
        x_api_key: str = Header(...),
    ):
        """
        Загрузить файл в S3.

        :param file: Файл для загрузки.
        :param service: Сервис для работы с S3.
        :param x_api_key: API-ключ для аутентификации.
        :return: Загруженный файл.
        """
        content = await file.read()
        await self.service.upload_file_object(
            key=str(uuid.uuid4()), original_filename=file.filename, content=content
        )
        return file

    @storage_router.get(
        "/download_file/{file_uuid}",
        status_code=status.HTTP_200_OK,
        summary="Скачать файл из S3",
        operation_id="getDownloadFileByUuidUnique",
    )
    @route_limiter
    @handle_routes_errors
    async def download_file(
        self,
        request: Request,
        file_uuid: str,
        x_api_key: str = Header(...),
    ):
        """
        Скачать файл из S3.

        :param file_uuid: UUID файла.
        :param service: Сервис для работы с S3.
        :param x_api_key: API-ключ для аутентификации.
        :return: Потоковый ответ с содержимым файла.
        """
        return await get_streaming_response(file_uuid, self.service)

    @storage_router.post(
        "/delete_file/",
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Удалить файл из S3",
        operation_id="deleteFileByUuidUnique",
    )
    @route_limiter
    @handle_routes_errors
    async def delete_file(
        self,
        request: Request,
        file_uuid: str,
        x_api_key: str = Header(...),
    ):
        """
        Удалить файл из S3.

        :param file_uuid: UUID файла.
        :param service: Сервис для работы с S3.
        :param x_api_key: API-ключ для аутентификации.
        :return: Нет возвращаемого значения (статус-код 204 No Content).
        """
        await self.service.delete_file_object(key=file_uuid)

    @storage_router.get(
        "/get_download_link_file/{file_uuid}",
        status_code=status.HTTP_200_OK,
        summary="Получить ссылку на скачивание файла из S3",
        operation_id="getDownloadLinkFileUnique",
    )
    @route_limiter
    @handle_routes_errors
    async def get_download_link_file(
        self,
        request: Request,
        file_uuid: str,
        x_api_key: str = Header(...),
    ):
        """
        Получить ссылку для скачивания файла из S3.

        :param file_uuid: UUID файла.
        :param service: Сервис для работы с S3.
        :param x_api_key: API-ключ для аутентификации.
        :return: Ссылка для скачивания файла.
        """
        return await self.service.generate_download_url(key=file_uuid)
