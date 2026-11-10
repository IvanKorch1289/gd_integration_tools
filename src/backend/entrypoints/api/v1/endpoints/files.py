from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    Request,
    UploadFile,
    status,
)

from extensions.core_entities.files.schemas.filter import FileFilter
from extensions.core_entities.files.schemas.route import (  # S168 W15-17 P2-10
    FileSchemaIn,
    FileSchemaOut,
    FileVersionSchemaOut,
)
from src.backend.entrypoints.api.dependencies.auth import require_api_key
from src.backend.entrypoints.api.generator.actions import (
    ActionRouterBuilder,
    ActionSpec,
    CrudSpec,
)
from src.backend.entrypoints.dependencies.rate_limit import get_default_rate_limiter
from src.backend.services.io.files import get_file_service

__all__ = (
    "ALLOWED_UPLOAD_CONTENT_TYPES",
    "MAX_STREAM_UPLOAD_BYTES",
    "MAX_UPLOAD_BYTES",
    "router",
    "storage_router",
)


router = APIRouter()
storage_router = APIRouter()

# ── ADR-0422: лимиты загрузки ─────────────────────────────────────────── #
#
# До ADR-0422 ``upload_file_handler`` делал ``await file.read()`` — весь
# файл целиком попадал в RAM без ограничения размера и без проверки
# content-type. Один запрос мог исчерпать память процесса.
#
# Теперь размер ограничен сверху, тело читается чанками, а неподдерживаемый
# content-type отклоняется до чтения тела.

#: Максимальный размер файла для буферизованной загрузки (64 MiB).
MAX_UPLOAD_BYTES: int = 64 * 1024 * 1024

#: Максимальный размер файла для streaming-загрузки (1 GiB).
#:
#: Streaming-эндпоинт создан для больших файлов (multipart-части по 8 MiB),
#: поэтому его лимит выше, чем у буферизованного (там тело целиком
#: попадает в RAM).
MAX_STREAM_UPLOAD_BYTES: int = 1024 * 1024 * 1024

#: Размер чанка при чтении загруженного файла (1 MiB).
_UPLOAD_CHUNK_SIZE: int = 1024 * 1024

#: Allowlist content-type для загрузки файлов.
#:
#: Покрывает документы, текст, изображения и бинарный fallback
#: (``application/octet-stream``). Исполняемые файлы, скрипты и HTML
#: отклоняются — загрузка проходит через AV-сервис, но тип файла должен
#: быть заранее известен.
ALLOWED_UPLOAD_CONTENT_TYPES: frozenset[str] = frozenset(
    {
        "application/json",
        "application/msword",
        "application/octet-stream",
        "application/pdf",
        "application/rtf",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/xml",
        "image/gif",
        "image/jpeg",
        "image/png",
        "image/tiff",
        "image/webp",
        "text/csv",
        "text/markdown",
        "text/plain",
    }
)

# Создаем билдеры для двух роутеров
crud_builder = ActionRouterBuilder(router)
storage_builder = ActionRouterBuilder(storage_router)

common_dependencies = [Depends(require_api_key), Depends(get_default_rate_limiter())]


def _ensure_content_type_allowed(content_type: str | None) -> str:
    """Проверить content-type по allowlist'у.

    Args:
        content_type: Content-type загружаемого файла (может быть ``None``).

    Returns:
        Нормализованный content-type (без параметров, в нижнем регистре).

    Raises:
        HTTPException: 415 — тип не указан или не входит в allowlist.

    """
    if not content_type:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Content-Type обязателен для загрузки файла",
        )
    normalized = content_type.split(";")[0].strip().lower()
    if normalized not in ALLOWED_UPLOAD_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"Content-Type {normalized!r} не поддерживается. "
                f"Разрешены: {sorted(ALLOWED_UPLOAD_CONTENT_TYPES)}"
            ),
        )
    return normalized


async def _read_limited(file: UploadFile, limit: int) -> bytes:
    """Прочитать файл чанками, не превышая ``limit`` байт.

    Args:
        file: Загруженный файл.
        limit: Максимальный размер в байтах.

    Returns:
        Содержимое файла.

    Raises:
        HTTPException: 413 — файл больше лимита.

    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_UPLOAD_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=(f"Файл превышает лимит {limit} байт (уже прочитано {total})"),
            )
        chunks.append(chunk)
    return b"".join(chunks)


async def _limited_stream(
    stream: AsyncIterator[bytes], limit: int
) -> AsyncIterator[bytes]:
    """Пропустить поток, прервав его при превышении ``limit`` байт.

    Args:
        stream: Исходный поток тела запроса.
        limit: Максимальный размер в байтах.

    Yields:
        Чанки исходного потока.

    Raises:
        HTTPException: 413 — поток больше лимита.

    """
    total = 0
    async for chunk in stream:
        total += len(chunk)
        if total > limit:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=(f"Тело превышает лимит {limit} байт (уже прочитано {total})"),
            )
        yield chunk


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
        tags=("Files",),
        id_param_name="object_id",
        id_field_name="id",
        default_order_by="id",
    )
)


# --- Storage API (storage_router) ---
# Wave 6.5a: instances инфраструктурных сервисов резолвятся через
# core.di.providers (lazy importlib), что снимает entrypoints → infra.


def get_s3_service() -> Any:
    """S3-сервис singleton — через DI provider."""
    from src.backend.core.di.providers import get_s3_service_provider

    return get_s3_service_provider()


def get_av_service() -> Any:
    """Antivirus-сервис singleton — через DI provider."""
    from src.backend.core.di.providers import get_antivirus_service_provider

    return get_antivirus_service_provider()


# Вспомогательный обработчик (wrapper) для загрузки файла,
# так как ActionSpec по умолчанию вызывает методы сервиса напрямую,
# а в старом CBV была кастомная логика формирования ответа.
async def upload_file_handler(
    request: Request,
    file: UploadFile = File(...),
    multipart_field_name: str | None = None,
    x_api_key: str = Header(...),
) -> dict[str, Any]:
    """Загружает файл через AV-сервис (scan + upload) и возвращает метаданные.

    ADR-0422: добавлены лимит размера (413 при превышении) и проверка
    content-type по allowlist'у (415). Файл читается чанками по 1 MiB —
    целиком в RAM больше не попадает.
    """
    av_service = get_av_service()
    _ensure_content_type_allowed(file.content_type)
    content = await _read_limited(file, MAX_UPLOAD_BYTES)

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
    endpoint=upload_file_handler,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
    summary="Проверить прикреплённый файл и сохранить в S3",
    operation_id="uploadFileStorageUploadFilePostUnique",
    dependencies=common_dependencies,
    tags=["Storage"],
)


async def upload_stream_handler(
    request: Request,
    x_api_key: str = Header(...),
    content_type: str | None = Header(default=None, alias="content-type"),
    x_filename: str | None = Header(default=None, alias="x-filename"),
) -> dict[str, Any]:
    """Streaming-аплоад больших файлов (S13 K2 W1).

    Принимает raw body как ``AsyncIterator[bytes]`` (``request.stream()``)
    и грузит чанками в S3 через ``put_object_multipart``. RAM-bound:
    1 chunk × 8MB ≈ 8MB peak вместо ``await file.read()``.

    ADR-0422: добавлен лимит размера (1 GiB, ``MAX_STREAM_UPLOAD_BYTES``).
    Превышение отсекается по ``Content-Length`` (без чтения тела) и по
    факту потока (413).

    ADR-0423: content-type проверяется по тому же allowlist'у, что и у
    буферизованной загрузки (415), и тоже **до** чтения тела. Content-type
    не передан — запрос принимается (прежний контракт).

    Заголовки:

    * ``content-type`` — MIME-type объекта;
    * ``x-filename`` — оригинальное имя файла (опционально);
    * ``x-api-key`` — auth.
    """
    if content_type:
        _ensure_content_type_allowed(content_type)
    s3_service = get_s3_service()
    s3_client: Any = getattr(s3_service, "_client", None) or s3_service
    key = (x_filename or "stream-upload").replace("/", "_")
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit():
        if int(content_length) > MAX_STREAM_UPLOAD_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=(
                    f"Тело превышает лимит {MAX_STREAM_UPLOAD_BYTES} байт "
                    f"(content-length={content_length})"
                ),
            )
    etag = await s3_client.put_object_multipart(
        key=key,
        stream=_limited_stream(request.stream(), MAX_STREAM_UPLOAD_BYTES),
        content_type=content_type,
    )
    return {"uploaded": True, "key": key, "etag": etag, "content_type": content_type}


storage_router.add_api_route(
    path="/upload-stream",
    endpoint=upload_stream_handler,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
    summary="Streaming upload больших файлов через S3 multipart (S13 K2 W1)",
    operation_id="uploadFileStreamS3MultipartUnique",
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
            tags=("Storage",),
            argument_aliases={"file_uuid": "key"},
        ),
        # ADR-0438: операции по КЛЮЧУ (без file_uuid) — порталу «Файлы S3»
        # нужен список объектов и чтение/ссылка по ключу, а не по uuid.
        ActionSpec(
            name="list_files",
            method="GET",
            path="/list",
            summary="Список объектов S3 по префиксу",
            service_getter=get_s3_service,
            service_method="list_files",
            dependencies=common_dependencies,
            tags=("Storage",),
        ),
        ActionSpec(
            name="get_file_by_key",
            method="GET",
            path="/get",
            summary="Получить файл в base64 по ключу",
            service_getter=get_s3_service,
            service_method="get_file_base64",
            dependencies=common_dependencies,
            tags=("Storage",),
        ),
        ActionSpec(
            name="download_by_key",
            method="GET",
            path="/download",
            summary="Получить ссылку на скачивание файла по ключу",
            service_getter=get_s3_service,
            service_method="generate_download_url",
            dependencies=common_dependencies,
            tags=("Storage",),
        ),
        ActionSpec(
            name="scan_file_in_antivirus",
            method="POST",
            path="/scan_file/{file_uuid}",
            summary="Проверить файл из S3 антивирусом",
            service_getter=get_av_service,
            service_method="scan_s3_file",
            dependencies=common_dependencies,
            tags=("Storage",),
            argument_aliases={"file_uuid": "key"},
        ),
    ]
)
