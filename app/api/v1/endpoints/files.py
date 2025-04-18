import uuid

from fastapi import APIRouter, File, Header, Request, UploadFile, status
from fastapi_utils.cbv import cbv

from app.api.routers_factory import create_router_class
from app.schemas.filter_schemas.files import FileFilter
from app.schemas.route_schemas.files import FileSchemaIn
from app.services.infra_services.s3 import get_s3_service_dependency
from app.services.route_services.files import get_file_service
from app.utils.decorators.limiting import route_limiting


__all__ = (
    "router",
    "storage_router",
)


storage_router = APIRouter()


@cbv(storage_router)
class StorageCBV:
    """
    CBV-класс для работы с файлами в S3.

    Предоставляет методы для загрузки, скачивания, удаления и получения ссылок на файлы.
    """

    service = get_s3_service_dependency()

    @storage_router.post(
        "/upload_file",
        status_code=status.HTTP_201_CREATED,
        summary="Добавить файл в S3",
        operation_id="uploadFileStorageUploadFilePostUnique",
    )
    @route_limiting
    async def upload_file_in_s3(
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
        key = str(uuid.uuid4())
        await self.service.upload_file(
            key=key,
            original_filename=file.filename,
            content=content,
        )
        return {
            "filename": file.filename,
            "key": key,
            "size": file.size,
            "headers": {
                "content-disposition": file.headers.get("content-disposition"),
                "content-type": file.headers.get("content-type"),
            },
        }

    @storage_router.get(
        "/download_file/{file_uuid}",
        status_code=status.HTTP_200_OK,
        summary="Скачать файл из S3",
        operation_id="getDownloadFileByUuidUnique",
    )
    @route_limiting
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
        return await self.service.download_file(key=file_uuid)

    @storage_router.post(
        "/delete_file/",
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Удалить файл из S3",
        operation_id="deleteFileByUuidUnique",
    )
    @route_limiting
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
    @route_limiting
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

    @storage_router.get(
        "/get_file_base64/{file_uuid}",
        status_code=status.HTTP_200_OK,
        summary="Получить файл в формате base64",
        operation_id="getFileBase64Unique",
    )
    @route_limiting
    async def get_file_base64(
        self,
        request: Request,
        file_uuid: str,
        x_api_key: str = Header(...),
    ):
        """
        Получить файл в формате base64.

        :param file_uuid: UUID файла.
        :param service: Сервис для работы с S3.
        :param x_api_key: API-ключ для аутентификации.
        :return: Файл в формате base64.
        """

        return await self.service.get_file_base64(key=file_uuid)


router = APIRouter()


FileCBV = create_router_class(
    router=router,
    schema_in=FileSchemaIn,
    service=get_file_service(),
    filter_class=FileFilter,
)
