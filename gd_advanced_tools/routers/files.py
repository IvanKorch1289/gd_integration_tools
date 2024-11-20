import uuid
from fastapi import APIRouter, File, Response, UploadFile, status
from fastapi_filter import FilterDepends
from fastapi_utils.cbv import cbv

from gd_advanced_tools.core.storage import s3_bucket_service_factory
from gd_advanced_tools.filters import FileFilter
from gd_advanced_tools.schemas import FileSchemaIn
from gd_advanced_tools.services import FileService


__all__ = ('router', 'storage_router', )


router = APIRouter()


@cbv(router)
class FileCBV:
    """CBV-класс для работы с файлами."""

    service = FileService()

    @router.get(
        '/all/',
        status_code=status.HTTP_200_OK,
        summary='Получить все файлы'
    )
    async def get_kinds(self):
        return await self.service.all()

    @router.get(
        '/id/{kind_id}',
        status_code=status.HTTP_200_OK,
        summary='Получить файл по ID'
    )
    async def get_kind(self, kind_id: int):
        return await self.service.get(key='id', value=kind_id)

    @router.get(
        '/get-by-filter',
        status_code=status.HTTP_200_OK,
        summary='Получить файл по полю'
    )
    async def get_by_filter(
        self,
        order_kind_filter: FileFilter = FilterDepends(FileFilter)
    ):
        return await self.service.get_by_params(
            filter=order_kind_filter
        )

    @router.post(
        '/create/',
        status_code=status.HTTP_201_CREATED,
        summary='Добавить файл'
    )
    async def add_kind(self, schema: FileSchemaIn):
        return await self.service.add(data=schema.model_dump())

    @router.put(
        '/update/{kind_id}',
        status_code=status.HTTP_200_OK,
        summary='Изменить файл по ID'
    )
    async def update_kind(self, schema: FileSchemaIn, kind_id: int):
        return await self.service.update(
            key='id',
            value=kind_id,
            data=schema.model_dump()
        )

    @router.delete(
        '/delete/{kind_id}',
        status_code=status.HTTP_204_NO_CONTENT,
        summary='Удалить файл по ID')
    async def delete_kind(self, kind_id: int):
        return await self.service.delete(key='id', value=kind_id)


storage_router = APIRouter()


@storage_router.post(
    '/upload_file',
    status_code=status.HTTP_201_CREATED,
    summary='Добавить файл',
)
async def upload_file(object_id: int, file: UploadFile = File(...)):
    service = s3_bucket_service_factory()
    content = await file.read()
    await service.upload_file_object(
        key=str(uuid.uuid4()),
        content=content
    )
    return file

# @storage_router.get(
#     '/download_file/{file_id}',
#     status_code=status.HTTP_200_OK,
#     summary='Скачать файл'
# )
# async def download_file(file_id: int):
#     response = await fs.get_file_object(key=key)
#     async with response['Body'] as stream:
#         data = await stream.read()
#         return Response(content=data, media_type='application/octet-stream')
