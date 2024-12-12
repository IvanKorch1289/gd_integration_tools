import uuid

from fastapi import APIRouter, Depends, File, UploadFile, status
from fastapi_filter import FilterDepends
from fastapi_utils.cbv import cbv

from backend.core.dependencies import get_streaming_response
from backend.core.storage import S3Service, s3_bucket_service_factory
from backend.files.filters import FileFilter
from backend.files.schemas import FileSchemaIn
from backend.files.service import FileService


__all__ = (
    "router",
    "storage_router",
)


router = APIRouter()


@cbv(router)
class FileCBV:
    """CBV-класс для работы с файлами в БД."""

    service = FileService()

    @router.get("/all/", status_code=status.HTTP_200_OK, summary="Получить все файлы")
    async def get_files(self):
        return await self.service.all()

    @router.get(
        "/id/{file_id}", status_code=status.HTTP_200_OK, summary="Получить файл по ID"
    )
    async def get_file(self, file_id: int):
        return await self.service.get(key="id", value=file_id)

    @router.get(
        "/get-by-filter",
        status_code=status.HTTP_200_OK,
        summary="Получить файл по полю",
    )
    async def get_by_filter(self, file_filter: FileFilter = FilterDepends(FileFilter)):
        return await self.service.get_by_params(filter=file_filter)

    @router.post(
        "/create/", status_code=status.HTTP_201_CREATED, summary="Добавить файл"
    )
    async def add_file(self, request_schema: FileSchemaIn):
        return await self.service.add(data=request_schema.model_dump())

    @router.put(
        "/update/{file_id}",
        status_code=status.HTTP_200_OK,
        summary="Изменить файл по ID",
    )
    async def update_file(self, request_schema: FileSchemaIn, file_id: int):
        return await self.service.update(
            key="id", value=file_id, data=request_schema.model_dump()
        )

    @router.delete(
        "/delete/{file_id}",
        status_code=status.HTTP_200_OK,
        summary="Удалить файл по ID",
    )
    async def delete_file(self, file_id: int):
        return await self.service.delete(key="id", value=file_id)


storage_router = APIRouter()


@cbv(storage_router)
class StorageCBV:
    """CBV-класс для работы с файлами в S3."""

    @storage_router.post(
        "/upload_file",
        status_code=status.HTTP_201_CREATED,
        summary="Добавить файл",
        operation_id="uploadFileStorageUploadFilePost",
    )
    async def upload_file(
        self,
        file: UploadFile = File(...),
        service: S3Service = Depends(s3_bucket_service_factory),
    ):
        """Загрузка файла в S3.

        :param file: Файл, который нужно загрузить.
        :param service: Сервис для работы с S3.
        :return: Загруженный файл.
        """
        content = await file.read()
        await service.upload_file_object(
            key=str(uuid.uuid4()), original_filename=file.filename, content=content
        )
        return file

    @storage_router.get(
        "/download_file/{file_uuid}",
        status_code=status.HTTP_200_OK,
        summary="Скачать файл",
        operation_id="getDownloadFileByUuid",
    )
    async def download_file(
        self,
        file_uuid: str,
        service: S3Service = Depends(s3_bucket_service_factory),
    ):
        """Скачивание файла из S3.

        :param file_uuid: UUID файла.
        :param service:param Сервис для работы с S3.
        :return: Потоковый ответ с содержимым файла.
        """
        return await get_streaming_response(file_uuid, service)

    @storage_router.post(
        "/delete_file/",
        status_code=status.HTTP_204_NO_CONTENT,  # Изменил статус-код на 204 No Content, так как удаление обычно не возвращает тело ответа
        summary="Удалить файл",
        operation_id="deleteFileByUuid",
    )
    async def delete_file(
        self,
        file_uuid: str,
        service: S3Service = Depends(s3_bucket_service_factory),
    ):
        """Удаление файла из S3.

        :param file_uuid: UUID файла.
        :param service: Сервис для работы с S3.
        :return: Нет возврата, так как статус-код 204 No Content.
        """
        await service.delete_file_object(key=file_uuid)

    @storage_router.get(
        "/get_download_link_file/{file_uuid}",
        status_code=status.HTTP_200_OK,
        summary="Получить ссылку на скачивание файла",
        operation_id="getDownloadLinkFile",
    )
    async def get_download_link_file(
        self,
        file_uuid: str,
        service: S3Service = Depends(s3_bucket_service_factory),
    ):
        """Получение ссылки на скачивание файла из S3.

        :param file_uuid: UUID файла.
        :param service: Сервис для работы с S3.
        :return: Ссылку на скачивание файла.
        """
        return await service.generate_download_url(key=file_uuid)
