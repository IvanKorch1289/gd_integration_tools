import uuid

from fastapi import APIRouter, Depends, File, UploadFile, status
from fastapi_filter import FilterDepends
from fastapi_utils.cbv import cbv

from gd_advanced_tools.core.dependencies import get_streaming_response
from gd_advanced_tools.core.storage import S3Service, s3_bucket_service_factory
from gd_advanced_tools.core.utils import utilities
from gd_advanced_tools.files.filters import FileFilter
from gd_advanced_tools.files.schemas import FileSchemaIn
from gd_advanced_tools.files.service import FileService


__all__ = (
    "router",
    "storage_router",
)


router = APIRouter()


@cbv(router)
class FileCBV:
    """CBV-класс для работы с файлами."""

    service = FileService()

    @router.get("/all/", status_code=status.HTTP_200_OK, summary="Получить все файлы")
    @utilities.caching
    async def get_files(self):
        return await self.service.all()

    @router.get(
        "/id/{file_id}", status_code=status.HTTP_200_OK, summary="Получить файл по ID"
    )
    @utilities.caching
    async def get_file(self, file_id: int):
        return await self.service.get(key="id", value=file_id)

    @router.get(
        "/get-by-filter",
        status_code=status.HTTP_200_OK,
        summary="Получить файл по полю",
    )
    @utilities.caching
    async def get_by_filter(self, file_filter: FileFilter = FilterDepends(FileFilter)):
        return await self.service.get_by_params(filter=file_filter)

    @router.post(
        "/create/", status_code=status.HTTP_201_CREATED, summary="Добавить файл"
    )
    @utilities.caching
    async def add_file(self, request_schema: FileSchemaIn):
        return await self.service.add(data=request_schema.model_dump())

    @router.put(
        "/update/{file_id}",
        status_code=status.HTTP_200_OK,
        summary="Изменить файл по ID",
    )
    @utilities.caching
    async def update_file(self, request_schema: FileSchemaIn, file_id: int):
        return await self.service.update(
            key="id", value=file_id, data=request_schema.model_dump()
        )

    @router.delete(
        "/delete/{file_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Удалить файл по ID",
    )
    @utilities.caching
    async def delete_file(self, file_id: int):
        return await self.service.delete(key="id", value=file_id)


storage_router = APIRouter()


@storage_router.post(
    "/upload_file",
    status_code=status.HTTP_201_CREATED,
    summary="Добавить файл",
    operation_id="uploadFileStorageUploadFilePost",
)
async def upload_file(
    file: UploadFile = File(...),
    service: S3Service = Depends(s3_bucket_service_factory),
):
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
    file_uuid: str, service: S3Service = Depends(s3_bucket_service_factory)
):
    return await get_streaming_response(file_uuid, service)


@storage_router.post(
    "/delete_file",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить файл",
    operation_id="deleteFileByUuid",
)
async def delete_file(
    file_uuid: str, service: S3Service = Depends(s3_bucket_service_factory)
):
    return await service.delete_file_object(key=file_uuid)
