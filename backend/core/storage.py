import json
import sys
import traceback
from contextlib import asynccontextmanager
from datetime import datetime
from io import BytesIO
from typing import Any, Union

from aiobotocore.response import StreamingBody
from aiobotocore.session import get_session
from aiohttp import ClientError

from backend.core.logging_config import fs_logger
from backend.core.settings import settings


class LogField:
    TIMESTAMP = "timestamp"
    OPERATION = "operation"
    DETAILS = "details"
    BUCKET = "bucket"
    ENDPOINT = "endpoint"
    EXCEPTION = "exception"


class S3Service:
    def __init__(
        self,
        bucket_name: str,
        endpoint: str,
        access_key: str,
        secret_key: str,
    ):
        self.bucket_name = bucket_name
        self.endpoint = endpoint
        self.access_key = access_key
        self.secret_key = secret_key

    @asynccontextmanager
    async def _create_s3_client(self):
        session = get_session()
        async with session.create_client(
            "s3",
            endpoint_url=self.endpoint,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
        ) as client:
            yield client

    async def upload_file_object(
        self, key: str, original_filename: str, content: Union[str, bytes]
    ) -> None:
        async with self._create_s3_client() as client:
            if isinstance(content, bytes):
                buffer = BytesIO(content)
            else:
                buffer = BytesIO(content.encode("utf-8"))
            metadata = {"x-amz-meta-original-filename": original_filename}
            try:
                await client.put_object(
                    Bucket=self.bucket_name, Key=key, Body=buffer, Metadata=metadata
                )
                await self.log_operation(
                    operation="upload_file_object",
                    details=f"Key: {key}, OriginalFilename: {original_filename}, ContentLength: {len(buffer.getvalue())}",
                )
                return {"upload_file_object": "success"}
            except Exception as ex:
                await self.log_operation(
                    operation="upload_file_object", exception=f"Error: {ex}"
                )

    async def list_objects(self) -> list[str]:
        async with self._create_s3_client() as client:
            response = await client.list_objects_v2(
                Bucket=self.bucket_name,
            )
            storage_content: list[str] = []

            try:
                contents = response["Contents"]
            except KeyError:
                return storage_content

            for item in contents:
                storage_content.append(item["Key"])

            return storage_content

    async def get_file_object(self, key: str) -> StreamingBody | None:
        async with self._create_s3_client() as client:
            try:
                file_obj = await client.get_object(Bucket=self.bucket_name, Key=key)
                body = file_obj.get("Body")
                metadata = file_obj.get("Metadata", {})
                return body, metadata
            except ClientError as ex:
                if ex.response["Error"]["Code"] == "NoSuchKey":
                    return None
                raise ex

    async def delete_file_object(self, key: str) -> None:
        async with self._create_s3_client() as client:
            try:
                await client.delete_object(Bucket=self.bucket_name, Key=key)
                await self.log_operation(
                    operation="delete_file_object", details="success"
                )
                return {"delete_file_object": "success"}
            except Exception as ex:
                await self.log_operation(
                    operation="delete_file_object", exception=f"Error: {ex}"
                )

    async def log_operation(
        self,
        operation: str,
        details: str | None = None,
        exception: Exception | None = None,
    ) -> None:
        log_data: dict[str, Any] = {
            LogField.TIMESTAMP: datetime.now().isoformat(),
            LogField.OPERATION: operation,
            LogField.DETAILS: details,
            LogField.BUCKET: self.bucket_name,
            LogField.ENDPOINT: self.endpoint,
        }

        if exception:
            log_data[LogField.EXCEPTION] = "".join(
                traceback.format_exception(
                    type(exception), exception, exception.__traceback__
                )
            )

        try:
            fs_logger.info(json.dumps(log_data))
        except Exception:
            traceback.print_exc(file=sys.stdout)


def s3_bucket_service_factory() -> S3Service:
    return S3Service(
        bucket_name=settings.storage_settings.fs_bucket,
        endpoint=settings.storage_settings.fs_endpoint,
        access_key=settings.storage_settings.fs_access_key,
        secret_key=settings.storage_settings.fs_secret_key,
    )
