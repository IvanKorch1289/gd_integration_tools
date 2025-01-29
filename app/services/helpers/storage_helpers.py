import io
import os
from typing import Any, Dict, List

import base64
import tempfile
import zipfile
from fastapi.responses import StreamingResponse

from app.infra.storage import BaseS3Service


__all__ = (
    "get_streaming_response",
    "get_base64_file",
    "create_zip_streaming_response",
)


async def process_file(key: str, service: BaseS3Service) -> Dict[str, Any]:
    """
    Получает файл из S3 и возвращает его в виде потокового генератора.

    Args:
        file_uuid (str): Уникальный идентификатор файла в S3.
        service (S3Service): Сервис для работы с S3.

    Returns:
        Dict[str, Any]: Словарь, содержащий потоковый генератор, медиа-тип и заголовки.

    Raises:
        HTTPException: Если файл не найден в S3.
    """
    streaming_body, metadata = await service.get_file_object(key=key)
    if not streaming_body:
        raise ValueError("File not found")

    original_filename = metadata.get("x-amz-meta-original-filename", "")

    async def stream_generator():
        async for chunk in streaming_body.iter_chunks():
            yield chunk

    headers = {}
    if original_filename:
        headers["Content-Disposition"] = f"attachment; filename={original_filename}"

    return {
        "body": stream_generator(),
        "media_type": "application/octet-stream",
        "headers": headers,
    }


async def get_streaming_response(key: str) -> StreamingResponse:
    """
    Возвращает потоковый ответ для скачивания файла.

    Args:
        file_uuid (str): Уникальный идентификатор файла в S3.
        service (S3Service): Сервис для работы с S3.

    Returns:
        StreamingResponse: Потоковый ответ FastAPI для скачивания файла.
    """
    file_info = await process_file(key=key)
    return StreamingResponse(
        file_info["body"],
        media_type=file_info["media_type"],
        headers=file_info["headers"],
    )


async def get_base64_file(key: str, service: BaseS3Service) -> str:
    """
    Возвращает содержимое файла в виде строки base64.

    Args:
        file_uuid (str): Уникальный идентификатор файла в S3.
        service (S3Service): Сервис для работы с S3.

    Returns:
        str: Содержимое файла в формате base64.
    """
    content = await service.get_file_bytes(key=key)
    if not content:
        raise ValueError("File not found")
    return base64.b64encode(content).decode("utf-8")


async def create_zip_streaming_response(
    keys: List[str], service: BaseS3Service
) -> StreamingResponse:
    """
    Создает ZIP-архив из списка файлов и возвращает его в виде потокового ответа.

    Args:
        files (List[str]): Список уникальных идентификаторов файлов в S3.
        service (S3Service): Сервис для работы с S3.

    Returns:
        StreamingResponse: Потоковый ответ FastAPI для скачивания ZIP-архива.

    Raises:
        HTTPException: Если произошла ошибка при обработке одного из файлов.
    """
    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, "w") as archive:
        for key in keys:
            content = await service.get_file_bytes(key=key)
            if not content:
                continue

            filename = await service.get_original_filename(key) or key
            with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                temp_file.write(content)
                temp_path = temp_file.name

            archive.write(temp_path, arcname=filename)
            os.unlink(temp_path)

    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=archive.zip"},
    )
