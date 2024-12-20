import io
import os
from typing import List

import base64
import tempfile
import zipfile
from fastapi import Depends, HTTPException
from fastapi.responses import StreamingResponse

from backend.core.storage import S3Service, s3_bucket_service_factory


async def process_file(
    file_uuid: str, service: S3Service = Depends(s3_bucket_service_factory)
):
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
):
    file_info = await process_file(file_uuid, service)
    return StreamingResponse(
        file_info["body"],
        media_type=file_info["media_type"],
        headers=file_info["headers"],
    )


async def get_base64_file(
    file_uuid: str, service: S3Service = Depends(s3_bucket_service_factory)
):
    file_info = await process_file(file_uuid, service)
    encoded_data = b""
    async for chunk in file_info["body"]:
        encoded_data += chunk
    return base64.b64encode(encoded_data).decode("utf-8")


async def create_zip_streaming_response(
    files: List[str], service: S3Service = Depends(s3_bucket_service_factory)
) -> StreamingResponse:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as archive:
        for file_uuid in files:
            try:
                streaming_body, metadata = await process_file(
                    file_uuid=file_uuid, service=service
                )
                original_filename = metadata.get("x-amz-meta-original-filename", "")

                temp_file = tempfile.NamedTemporaryFile(delete=False)
                async for chunk in streaming_body.iter_chunks():
                    temp_file.write(chunk)
                temp_file.close()

                archive.write(temp_file.name, arcname=original_filename)

                os.unlink(temp_file.name)

            except Exception as e:
                return {f"error {file_uuid}": e}

    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=files.zip"},
    )
