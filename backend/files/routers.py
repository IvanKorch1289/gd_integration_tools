import uuid
from typing import List

from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    Request,
    UploadFile,
    status,
)
from fastapi_filter import FilterDepends
from fastapi_utils.cbv import cbv

from backend.core.dependencies import get_streaming_response
from backend.core.errors import handle_routes_errors
from backend.core.limiter import route_limiter
from backend.core.storage import S3Service, s3_bucket_service_factory
from backend.files.filters import FileFilter
from backend.files.schemas import (
    FileSchemaIn,
    FileSchemaOut,
    FileVersionSchemaOut,
)
from backend.files.service import FileService, get_file_service


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

    # Внедряем зависимость через конструктор
    def __init__(self, service: FileService = Depends(get_file_service)):
        self.service = service

    @router.get(
        "/all/",
        status_code=status.HTTP_200_OK,
        summary="Получить все файлы",
        response_model=List[FileSchemaOut],
    )
    @route_limiter
    @handle_routes_errors
    async def get_files(self, request: Request, x_api_key: str = Header(...)):
        """
        Получить все файлы из базы данных.

        :param x_api_key: API-ключ для аутентификации.
        :return: Список всех файлов.
        """
        return await self.service.all()

    @router.get(
        "/id/{file_id}",
        status_code=status.HTTP_200_OK,
        summary="Получить файл по ID",
        response_model=FileSchemaOut,
    )
    @route_limiter
    @handle_routes_errors
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
        response_model=List[FileSchemaOut],
    )
    @route_limiter
    @handle_routes_errors
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
        "/create/",
        status_code=status.HTTP_201_CREATED,
        summary="Добавить файл",
        response_model=FileSchemaOut,
    )
    @route_limiter
    @handle_routes_errors
    async def add_file(
        self,
        request_schema: FileSchemaIn,
        request: Request,
        x_api_key: str = Header(...),
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
        response_model=List[FileSchemaOut],
    )
    @route_limiter
    @handle_routes_errors
    async def add_many_files(
        self,
        request_schema: List[FileSchemaIn],
        request: Request,
        x_api_key: str = Header(...),
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
        response_model=FileSchemaOut,
    )
    @route_limiter
    @handle_routes_errors
    async def update_file(
        self,
        request_schema: FileSchemaIn,
        file_id: int,
        request: Request,
        x_api_key: str = Header(...),
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
    @route_limiter
    @handle_routes_errors
    async def delete_file(
        self, file_id: int, request: Request, x_api_key: str = Header(...)
    ):
        """
        Удалить файл по его ID.

        :param file_id: ID файла.
        :param x_api_key: API-ключ для аутентификации.
        :return: Сообщение об успешном удалении.
        """
        await self.service.delete(key="id", value=file_id)

    @router.get(
        "/all_versions/{file_id}",
        status_code=status.HTTP_200_OK,
        summary="Получить версии объекта данных файла по ID",
        response_model=List[FileVersionSchemaOut],
    )
    @route_limiter
    @handle_routes_errors
    async def get_all_file_versions(
        self, file_id: int, request: Request, x_api_key: str = Header(...)
    ):
        """
        Получить все версии объекта данных файла по его ID.

        :param file_id: ID данных файла.
        :param request: Объект запроса FastAPI.
        :param x_api_key: API-ключ для аутентификации.
        :return: Список всех версий объекта.
        :raises HTTPException: Если произошла ошибка при получении данных.
        """
        return await self.service.get_all_object_versions(object_id=file_id)

    @router.get(
        "/latest_version/{file_id}",
        status_code=status.HTTP_200_OK,
        summary="Получить последнюю версию объекта данных файла по ID",
        response_model=FileVersionSchemaOut,
    )
    @route_limiter
    @handle_routes_errors
    async def get_file_latest_version(
        self, file_id: int, request: Request, x_api_key: str = Header(...)
    ):
        """
        Получить последнюю версию объекта данных файла по его ID.

        :param file_id: ID данных файла.
        :param request: Объект запроса FastAPI.
        :param x_api_key: API-ключ для аутентификации.
        :return: Последняя версия объекта.
        :raises HTTPException: Если произошла ошибка при получении данных.
        """
        return await self.service.get_latest_object_version(object_id=file_id)

    @router.post(
        "/restore_to_version/{file_id}",
        status_code=status.HTTP_200_OK,
        summary="Восстановить объект данных файла до указанной версии",
        response_model=FileSchemaOut,
    )
    @route_limiter
    @handle_routes_errors
    async def restore_file_to_version(
        self,
        file_id: int,
        transaction_id: int,
        request: Request,
        x_api_key: str = Header(...),
    ):
        """
        Восстановить объект данных файла до указанной версии.

        :param file_id: ID данных файла.
        :param transaction_id: ID транзакции (версии) для восстановления.
        :param request: Объект запроса FastAPI.
        :param x_api_key: API-ключ для аутентификации.
        :return: Восстановленный объект.
        :raises HTTPException: Если произошла ошибка при восстановлении.
        """
        return await self.service.restore_object_to_version(
            object_id=file_id, transaction_id=transaction_id
        )

    @router.get(
        "/changes/{file_id}",
        status_code=status.HTTP_200_OK,
        summary="Получить изменения объекта данных файла по ID",
    )
    @route_limiter
    @handle_routes_errors
    async def get_file_changes(
        self, file_id: int, request: Request, x_api_key: str = Header(...)
    ):
        """
        Получить список изменений объекта данных файла по его ID.

        :param file_id: ID данных файла.
        :param request: Объект запроса FastAPI.
        :param x_api_key: API-ключ для аутентификации.
        :return: Список изменений объекта.
        :raises HTTPException: Если произошла ошибка при получении данных.
        """
        return await self.service.get_object_changes(object_id=file_id)


storage_router = APIRouter()


@cbv(storage_router)
class StorageCBV:
    """
    CBV-класс для работы с файлами в S3.

    Предоставляет методы для загрузки, скачивания, удаления и получения ссылок на файлы.
    """

    # Внедряем зависимость через конструктор
    def __init__(self, service: S3Service = Depends(s3_bucket_service_factory)):
        self.service = service

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
