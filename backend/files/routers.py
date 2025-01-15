import uuid
from typing import List

from fastapi import APIRouter, Depends, File, Header, UploadFile, status
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
    """
    CBV-класс для работы с файлами в базе данных.

    Предоставляет методы для получения, добавления, обновления и удаления файлов.
    """

    service = FileService()

    @router.get("/all/", status_code=status.HTTP_200_OK, summary="Получить все файлы")
    async def get_files(self, x_api_key: str = Header(...)):
        """
        Получить все файлы из базы данных.

        :param x_api_key: API-ключ для аутентификации.
        :return: Список всех файлов.
        """
        return await self.service.all()

    @router.get(
        "/id/{file_id}", status_code=status.HTTP_200_OK, summary="Получить файл по ID"
    )
    async def get_file(self, file_id: int, x_api_key: str = Header(...)):
        """
        Получить файл по его ID.

        :param file_id: ID файла.
        :param x_api_key: API-ключ для аутентификации.
        :return: Файл с указанным ID.
        """
        return await self.service.get(key="id", value=file_id)

    @router.get(
        "/get-by-filter",
        status_code=status.HTTP_200_OK,
        summary="Получить файл по фильтру",
    )
    async def get_by_filter(
        self,
        file_filter: FileFilter = FilterDepends(FileFilter),
        x_api_key: str = Header(...),
    ):
        """
        Получить файлы, соответствующие указанному фильтру.

        :param file_filter: Фильтр для поиска файлов.
        :param x_api_key: API-ключ для аутентификации.
        :return: Список файлов, соответствующих фильтру.
        """
        return await self.service.get_by_params(filter=file_filter)

    @router.post(
        "/create/", status_code=status.HTTP_201_CREATED, summary="Добавить файл"
    )
    async def add_file(
        self, request_schema: FileSchemaIn, x_api_key: str = Header(...)
    ):
        """
        Добавить новый файл в базу данных.

        :param request_schema: Данные для создания файла.
        :param x_api_key: API-ключ для аутентификации.
        :return: Созданный файл.
        """
        return await self.service.add(data=request_schema.model_dump())

    @router.post(
        "/create_many/",
        status_code=status.HTTP_201_CREATED,
        summary="Добавить несколько файлов",
    )
    async def add_many_files(
        self, request_schema: List[FileSchemaIn], x_api_key: str = Header(...)
    ):
        """
        Добавить несколько файлов в базу данных.

        :param request_schema: Список данных для создания файлов.
        :param x_api_key: API-ключ для аутентификации.
        :return: Список созданных файлов.
        """
        data_list = [schema.model_dump() for schema in request_schema]
        return await self.service.add_many(data_list=data_list)

    @router.put(
        "/update/{file_id}",
        status_code=status.HTTP_200_OK,
        summary="Изменить файл по ID",
    )
    async def update_file(
        self, request_schema: FileSchemaIn, file_id: int, x_api_key: str = Header(...)
    ):
        """
        Обновить файл по его ID.

        :param request_schema: Данные для обновления файла.
        :param file_id: ID файла.
        :param x_api_key: API-ключ для аутентификации.
        :return: Обновленный файл.
        """
        return await self.service.update(
            key="id", value=file_id, data=request_schema.model_dump()
        )

    @router.delete(
        "/delete/{file_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Удалить файл по ID",
    )
    async def delete_file(self, file_id: int, x_api_key: str = Header(...)):
        """
        Удалить файл по его ID.

        :param file_id: ID файла.
        :param x_api_key: API-ключ для аутентификации.
        :return: Сообщение об успешном удалении.
        """
        return await self.service.delete(key="id", value=file_id)


storage_router = APIRouter()


@cbv(storage_router)
class StorageCBV:
    """
    CBV-класс для работы с файлами в S3.

    Предоставляет методы для загрузки, скачивания, удаления и получения ссылок на файлы.
    """

    @storage_router.post(
        "/upload_file",
        status_code=status.HTTP_201_CREATED,
        summary="Добавить файл в S3",
        operation_id="uploadFileStorageUploadFilePostUnique",
    )
    async def upload_file(
        self,
        file: UploadFile = File(...),
        service: S3Service = Depends(s3_bucket_service_factory),
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
        await service.upload_file_object(
            key=str(uuid.uuid4()), original_filename=file.filename, content=content
        )
        return file

    @storage_router.get(
        "/download_file/{file_uuid}",
        status_code=status.HTTP_200_OK,
        summary="Скачать файл из S3",
        operation_id="getDownloadFileByUuidUnique",
    )
    async def download_file(
        self,
        file_uuid: str,
        service: S3Service = Depends(s3_bucket_service_factory),
        x_api_key: str = Header(...),
    ):
        """
        Скачать файл из S3.

        :param file_uuid: UUID файла.
        :param service: Сервис для работы с S3.
        :param x_api_key: API-ключ для аутентификации.
        :return: Потоковый ответ с содержимым файла.
        """
        return await get_streaming_response(file_uuid, service)

    @storage_router.post(
        "/delete_file/",
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Удалить файл из S3",
        operation_id="deleteFileByUuidUnique",
    )
    async def delete_file(
        self,
        file_uuid: str,
        service: S3Service = Depends(s3_bucket_service_factory),
        x_api_key: str = Header(...),
    ):
        """
        Удалить файл из S3.

        :param file_uuid: UUID файла.
        :param service: Сервис для работы с S3.
        :param x_api_key: API-ключ для аутентификации.
        :return: Нет возвращаемого значения (статус-код 204 No Content).
        """
        await service.delete_file_object(key=file_uuid)

    @storage_router.get(
        "/get_download_link_file/{file_uuid}",
        status_code=status.HTTP_200_OK,
        summary="Получить ссылку на скачивание файла из S3",
        operation_id="getDownloadLinkFileUnique",
    )
    async def get_download_link_file(
        self,
        file_uuid: str,
        service: S3Service = Depends(s3_bucket_service_factory),
        x_api_key: str = Header(...),
    ):
        """
        Получить ссылку для скачивания файла из S3.

        :param file_uuid: UUID файла.
        :param service: Сервис для работы с S3.
        :param x_api_key: API-ключ для аутентификации.
        :return: Ссылка для скачивания файла.
        """
        return await service.generate_download_url(key=file_uuid)
