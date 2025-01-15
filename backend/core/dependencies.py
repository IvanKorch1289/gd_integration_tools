import io
import os
from typing import Any, Dict, List

import base64
import tempfile
import zipfile
from fastapi import Depends, HTTPException
from fastapi.responses import StreamingResponse

from backend.core.storage import S3Service, s3_bucket_service_factory


async def process_file(
    file_uuid: str, service: S3Service = Depends(s3_bucket_service_factory)
) -> Dict[str, Any]:
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
    streaming_body, metadata = await service.get_file_object(key=file_uuid)

    if streaming_body is None:
        raise HTTPException(
            status_code=404, detail=f"File with key {file_uuid} not found"
        )

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


async def get_streaming_response(
    file_uuid: str, service: S3Service = Depends(s3_bucket_service_factory)
) -> StreamingResponse:
    """
    Возвращает потоковый ответ для скачивания файла.

    Args:
        file_uuid (str): Уникальный идентификатор файла в S3.
        service (S3Service): Сервис для работы с S3.

    Returns:
        StreamingResponse: Потоковый ответ FastAPI для скачивания файла.
    """
    file_info = await process_file(file_uuid, service)
    return StreamingResponse(
        file_info["body"],
        media_type=file_info["media_type"],
        headers=file_info["headers"],
    )


async def get_base64_file(
    file_uuid: str, service: S3Service = Depends(s3_bucket_service_factory)
) -> str:
    """
    Возвращает содержимое файла в виде строки base64.

    Args:
        file_uuid (str): Уникальный идентификатор файла в S3.
        service (S3Service): Сервис для работы с S3.

    Returns:
        str: Содержимое файла в формате base64.
    """
    file_info = await process_file(file_uuid, service)
    encoded_data = b""
    async for chunk in file_info["body"]:
        encoded_data += chunk
    return base64.b64encode(encoded_data).decode("utf-8")


async def create_zip_streaming_response(
    files: List[str], service: S3Service = Depends(s3_bucket_service_factory)
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
    with zipfile.ZipFile(buffer, mode="w") as archive:
        for file_uuid in files:
            try:
                file_info = await process_file(file_uuid=file_uuid, service=service)
                original_filename = (
                    file_info["headers"]
                    .get("Content-Disposition", "")
                    .split("filename=")[-1]
                )

                with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                    async for chunk in file_info["body"]:
                        temp_file.write(chunk)
                    temp_file_path = temp_file.name

                archive.write(temp_file_path, arcname=original_filename)
                os.unlink(temp_file_path)

            except Exception as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Error processing file {file_uuid}: {str(e)}",
                )

    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=files.zip"},
    )
