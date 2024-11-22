import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from fastapi_filter import FilterDepends
from fastapi_utils.cbv import cbv

from gd_advanced_tools.core.storage import S3Service, s3_bucket_service_factory
from gd_advanced_tools.filters import FileFilter
from gd_advanced_tools.schemas import FileSchemaIn
from gd_advanced_tools.services import FileService

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
    async def get_kinds(self):
        return await self.service.all()

    @router.get(
        "/id/{kind_id}", status_code=status.HTTP_200_OK, summary="Получить файл по ID"
    )
    async def get_kind(self, kind_id: int):
        return await self.service.get(key="id", value=kind_id)

    @router.get(
        "/get-by-filter",
        status_code=status.HTTP_200_OK,
        summary="Получить файл по полю",
    )
    async def get_by_filter(
        self, order_kind_filter: FileFilter = FilterDepends(FileFilter)
    ):
        return await self.service.get_by_params(filter=order_kind_filter)

    @router.post(
        "/create/", status_code=status.HTTP_201_CREATED, summary="Добавить файл"
    )
    async def add_kind(self, request_schema: FileSchemaIn):
        return await self.service.add(data=request_schema.model_dump())

    @router.put(
        "/update/{kind_id}",
        status_code=status.HTTP_200_OK,
        summary="Изменить файл по ID",
    )
    async def update_kind(self, request_schema: FileSchemaIn, kind_id: int):
        return await self.service.update(
            key="id", value=kind_id, data=request_schema.model_dump()
        )

    @router.delete(
        "/delete/{kind_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Удалить файл по ID",
    )
    async def delete_kind(self, kind_id: int):
        return await self.service.delete(key="id", value=kind_id)


storage_router = APIRouter()


@storage_router.post(
    "/upload_file",
    status_code=status.HTTP_201_CREATED,
    summary="Добавить файл",
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
    "/download_file/{file_id}", status_code=status.HTTP_200_OK, summary="Скачать файл"
)
async def download_file(
    file_uuid: str, service: S3Service = Depends(s3_bucket_service_factory)
):
    streaming_body, metadata = await service.get_file_object(key=file_uuid)

    if streaming_body is None:
        raise HTTPException(
            status_code=404, detail=f"Файл с ключом {file_uuid} не найден"
        )

    original_filename = metadata.get("x-amz-meta-original-filename", "")

    async def stream_generator():
        async for chunk in streaming_body.iter_chunks():
            yield chunk

    headers = {}
    if original_filename:
        headers["Content-Disposition"] = f"attachment; filename={original_filename}"

    return StreamingResponse(
        stream_generator(), media_type="application/octet-stream", headers=headers
    )


@storage_router.post(
    "/delete_file",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить файл",
)
async def delete_file(
    file_uuid: str, service: S3Service = Depends(s3_bucket_service_factory)
):
    return await service.delete_file_object(key=file_uuid)
