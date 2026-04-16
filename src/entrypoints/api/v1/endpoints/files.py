from typing import Any

from fastapi import APIRouter, Depends, File, Header, Request, UploadFile, status

from app.core.decorators.limiting import route_limiting
from app.entrypoints.api.dependencies.auth import require_api_key
from app.entrypoints.api.generator.actions import (
    ActionRouterBuilder,
    ActionSpec,
    CrudSpec,
)
from app.infrastructure.external_apis.antivirus import (
    AntivirusService,
    get_antivirus_service_dependency,
)
from app.infrastructure.external_apis.s3 import S3Service, get_s3_service_dependency
from app.schemas.filter_schemas.files import FileFilter
from app.schemas.route_schemas.files import (
    FileSchemaIn,
    FileSchemaOut,
    FileVersionSchemaOut,
)
from app.services.files import get_file_service

__all__ = ("router", "storage_router")


router = APIRouter()
storage_router = APIRouter()

# Создаем билдеры для двух роутеров
crud_builder = ActionRouterBuilder(router)
storage_builder = ActionRouterBuilder(storage_router)

common_dependencies = [Depends(require_api_key)]
common_decorators = [route_limiting]


# --- CRUD для метаданных файлов (router) ---
crud_builder.add_crud_resource(
    CrudSpec(
        name="files",
        service_getter=get_file_service,
        schema_in=FileSchemaIn,
        schema_out=FileSchemaOut,
        version_schema=FileVersionSchemaOut,
        filter_class=FileFilter,
        dependencies=common_dependencies,
        decorators=common_decorators,
        tags=("Files",),
        id_param_name="object_id",
        id_field_name="id",
        default_order_by="id",
    )
)


# --- Storage API (storage_router) ---
# Для storage_router нам нужны инстансы инфраструктурных сервисов.
# Поскольку ActionSpec ожидает service_getter, создадим фабрики.


def get_s3_service() -> S3Service:
    # Зависимость возвращает инстанс
    return next(get_s3_service_dependency())


def get_av_service() -> AntivirusService:
    # Зависимость возвращает инстанс
    return next(get_antivirus_service_dependency())


# Вспомогательный обработчик (wrapper) для загрузки файла,
# так как ActionSpec по умолчанию вызывает методы сервиса напрямую,
# а в старом CBV была кастомная логика формирования ответа.
async def upload_file_handler(
    request: Request,
    file: UploadFile = File(...),
    multipart_field_name: str | None = None,
    x_api_key: str = Header(...),
) -> dict[str, Any]:
    av_service = get_av_service()
    content = await file.read()

    result = await av_service.scan_and_upload_file(
        file_bytes=content,
        filename=file.filename or "uploaded_file",
        content_type=file.content_type,
        multipart_field_name=multipart_field_name,
    )

    return {
        "uploaded": result["uploaded"],
        "filename": result["filename"],
        "key": result["key"],
        "size": len(content),
        "headers": {
            "content-disposition": file.headers.get("content-disposition"),
            "content-type": file.content_type,
        },
        "scan_result": result["scan_result"],
    }


# Поскольку загрузка файла имеет кастомную логику с чтением из UploadFile,
# проще оставить её как обычный роут FastAPI, а остальные методы вынести в ActionSpec.
storage_router.add_api_route(
    path="/upload_file",
    endpoint=route_limiting(upload_file_handler),
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
    summary="Проверить прикреплённый файл и сохранить в S3",
    operation_id="uploadFileStorageUploadFilePostUnique",
    dependencies=common_dependencies,
    tags=["Storage"],
)


storage_builder.add_actions(
    [
        ActionSpec(
            name="download_file",
            method="GET",
            path="/download_file/{file_uuid}",
            summary="Скачать файл из S3",
            service_getter=get_s3_service,
            service_method="download_file",
            dependencies=common_dependencies,
            decorators=common_decorators,
            tags=("Storage",),
            argument_aliases={"file_uuid": "key"},
        ),
        ActionSpec(
            name="delete_file",
            method="POST",
            path="/delete_file/",
            summary="Удалить файл из S3",
            status_code=status.HTTP_204_NO_CONTENT,
            service_getter=get_s3_service,
            service_method="delete_file_object",
            dependencies=common_dependencies,
            decorators=common_decorators,
            tags=("Storage",),
            # Тут в старом эндпоинте file_uuid приходил из Query (поскольку путь без параметра),
            # так что argument_aliases смапит его в key для S3Service.
            argument_aliases={"file_uuid": "key"},
        ),
        ActionSpec(
            name="get_download_link_file",
            method="GET",
            path="/get_download_link_file/{file_uuid}",
            summary="Получить ссылку на скачивание файла из S3",
            service_getter=get_s3_service,
            service_method="generate_download_url",
            dependencies=common_dependencies,
            decorators=common_decorators,
            tags=("Storage",),
            argument_aliases={"file_uuid": "key"},
        ),
        ActionSpec(
            name="get_file_base64",
            method="GET",
            path="/get_file_base64/{file_uuid}",
            summary="Получить файл в формате base64",
            service_getter=get_s3_service,
            service_method="get_file_base64",
            dependencies=common_dependencies,
            decorators=common_decorators,
            tags=("Storage",),
            argument_aliases={"file_uuid": "key"},
        ),
        ActionSpec(
            name="scan_file_in_antivirus",
            method="POST",
            path="/scan_file/{file_uuid}",
            summary="Проверить файл из S3 антивирусом",
            service_getter=get_av_service,
            service_method="scan_s3_file",
            dependencies=common_dependencies,
            decorators=common_decorators,
            tags=("Storage",),
            argument_aliases={"file_uuid": "key"},
        ),
    ]
)
