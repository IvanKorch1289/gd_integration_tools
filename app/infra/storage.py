import json
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from datetime import datetime
from io import BytesIO
from typing import Any, AsyncGenerator, Optional, Tuple, Union

from aiobotocore.config import AioConfig
from aiobotocore.response import StreamingBody
from aiobotocore.session import get_session
from botocore.exceptions import ClientError as BotoClientError

from app.config.settings import FileStorageSettings, settings
from app.infra.redis import redis_client
from app.utils.decorators.caching import existence_cache, metadata_cache
from app.utils.logging_service import fs_logger


__all__ = (
    "MinioService",
    "BaseS3Service",
    "s3_bucket_service_factory",
)


class LogField:
    """Class for storing log field constants."""

    TIMESTAMP = "timestamp"
    OPERATION = "operation"
    DETAILS = "details"
    BUCKET = "bucket"
    ENDPOINT = "endpoint"
    EXCEPTION = "exception"


class BaseS3Service(ABC):
    @abstractmethod
    async def upload_file_object(
        self, key: str, original_filename: str, content: Union[str, bytes]
    ) -> dict:
        pass

    @abstractmethod
    async def list_objects(self) -> list[str]:
        pass

    @abstractmethod
    async def get_file_object(
        self, key: str
    ) -> Optional[Tuple[StreamingBody, dict]]:
        pass

    @abstractmethod
    async def delete_file_object(self, key: str) -> dict:
        pass

    @abstractmethod
    async def generate_download_url(
        self, key: str, expires_in: int = 3600
    ) -> Optional[str]:
        pass

    @abstractmethod
    async def check_bucket_exists(self) -> bool:
        pass

    @abstractmethod
    async def file_exists(self, key: str) -> bool:
        pass

    @abstractmethod
    async def get_file_info(self, key: str) -> Optional[dict]:
        pass

    @abstractmethod
    async def get_original_filename(self, key: str) -> Optional[str]:
        pass

    @abstractmethod
    async def get_file_bytes(self, key: str) -> Optional[bytes]:
        pass


class MinioService(BaseS3Service):
    """Class for interacting with Minio object storage service with connection lifecycle management."""

    def __init__(self, settings: FileStorageSettings):
        self._client: Optional[Any] = None
        self.settings = settings
        self.logger = fs_logger
        self._session = get_session()
        self._initialize_attributes()

    def _initialize_attributes(self):
        """Initializes configuration attributes from settings."""
        self.bucket = self.settings.bucket
        self.access_key = self.settings.access_key
        self.secret_key = self.settings.secret_key
        self.endpoint = self._get_endpoint()
        self.client_config = AioConfig(
            connect_timeout=self.settings.timeout,
            retries={"max_attempts": self.settings.retries},
            s3={
                "addressing_style": self._get_addressing_style(),
                "payload_signing_enabled": self.settings.provider == "aws",
            },
        )

    async def initialize_connection(self):
        """Establishes and verifies connection to object storage."""
        try:
            if self._client is not None:
                return

            self._client = await self._session.create_client(
                "s3",
                endpoint_url=self.endpoint,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                config=self.client_config,
                use_ssl=self.settings.use_ssl,
                verify=(
                    self.settings.ca_bundle if self.settings.verify else None
                ),
            ).__aenter__()

            if not await self.check_bucket_exists():
                raise RuntimeError(f"Bucket {self.bucket} not found")

            self.logger.info("Successfully connected to object storage")

        except Exception as exc:
            await self.shutdown()
            raise RuntimeError(
                f"Connection initialization failed: {str(exc)}"
            ) from exc

    async def shutdown(self):
        """Gracefully closes all connections and releases resources."""
        if self._client:
            try:
                await self._client.close()
                self.logger.info("Object storage connections closed")
            except Exception:
                self.logger.error("Error closing connections", exc_info=True)
            finally:
                self._client = None

    def _get_endpoint(self) -> Optional[str]:
        """Returns configured endpoint or None for AWS."""
        return (
            self.settings.endpoint if self.settings.provider != "aws" else None
        )

    def _get_addressing_style(self) -> str:
        """Returns the configured addressing style."""
        return getattr(self.settings, "fs_addressing_style", "path")

    @asynccontextmanager
    async def _get_client_context(self) -> AsyncGenerator:
        """Provides managed access to the S3 client with error handling."""
        if not self._client:
            raise RuntimeError("Connection not initialized")

        try:
            yield self._client
        except BotoClientError:
            self.logger.error("S3 API error", exc_info=True)
            raise
        except Exception:
            self.logger.error("Connection error", exc_info=True)
            await self.shutdown()
            raise

    async def upload_file_object(
        self, key: str, original_filename: str, content: Union[str, bytes]
    ) -> dict:
        """Uploads a file to object storage."""
        if not content:
            return {
                "status": "error",
                "message": "Empty content",
                "error": "No content provided for upload",
            }

        buffer = BytesIO(
            content if isinstance(content, bytes) else content.encode("utf-8")
        )

        async with self._get_client_context() as client:
            buffer.seek(0)
            metadata = {"x-amz-meta-original-filename": original_filename}
            try:
                await client.put_object(
                    Bucket=self.bucket,
                    Key=key,
                    Body=buffer,
                    Metadata=metadata,
                    ContentLength=len(buffer.getvalue()),
                )
                await self._invalidate_cache(key)
                return {"status": "success", "message": "File uploaded"}
            except Exception as exc:
                self.logger.error("Upload failed for {key}", exc_info=True)
                return {
                    "status": "error",
                    "message": "Upload failed",
                    "error": str(exc),
                }

    async def list_objects(self) -> list[str]:
        """Lists all objects in the bucket."""
        async with self._get_client_context() as client:
            try:
                response = await client.list_objects_v2(Bucket=self.bucket)
                return [item["Key"] for item in response.get("Contents", [])]
            except BotoClientError as exc:
                if exc.response["Error"]["Code"] == "NoSuchBucket":
                    return []
                raise

    async def get_file_object(
        self, key: str
    ) -> Optional[Tuple[StreamingBody, dict]]:
        """Retrieves an object from storage."""
        async with self._get_client_context() as client:
            try:
                response = await client.get_object(Bucket=self.bucket, Key=key)
                return response["Body"], response.get("Metadata", {})
            except BotoClientError as exc:
                if exc.response["Error"]["Code"] == "NoSuchKey":
                    return None
                raise

    async def delete_file_object(self, key: str) -> dict:
        """Deletes an object from storage."""
        async with self._get_client_context() as client:
            try:
                await client.delete_object(Bucket=self.bucket, Key=key)
                await self._invalidate_cache(key)
                return {"status": "success", "message": "File deleted"}
            except Exception as exc:
                return {
                    "status": "error",
                    "message": "Deletion failed",
                    "error": str(exc),
                }

    async def generate_download_url(
        self, key: str, expires_in: int = 3600
    ) -> Optional[str]:
        """Generates a presigned download URL."""
        async with self._get_client_context() as client:
            try:
                return await client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self.bucket, "Key": key},
                    ExpiresIn=expires_in,
                )
            except Exception:
                self.logger.error("URL generation failed", exc_info=True)
                return None

    @existence_cache
    async def file_exists(self, key: str) -> bool:
        """Checks if file exists in storage."""
        async with self._get_client_context() as client:
            try:
                await client.head_object(Bucket=self.bucket, Key=key)
                return True
            except BotoClientError as exc:
                if exc.response["Error"]["Code"] == "404":
                    return False
                raise
            except Exception as exc:
                await self.log_operation(
                    operation="file_exists",
                    details=f"Key: {key}",
                    exception=f"Existence check error: {str(exc)}",
                )
                raise

    @metadata_cache
    async def get_file_info(self, key: str) -> Optional[dict]:
        """Retrieves file metadata information."""
        async with self._get_client_context() as client:
            try:
                response = await client.head_object(
                    Bucket=self.bucket, Key=key
                )
                return {
                    "last_modified": response["LastModified"],
                    "content_length": response["ContentLength"],
                    "metadata": response.get("Metadata", {}),
                }
            except BotoClientError as exc:
                if exc.response["Error"]["Code"] == "404":
                    return None
                raise
            except Exception as exc:
                await self.log_operation(
                    operation="get_file_info",
                    details=f"Key: {key}",
                    exception=f"Metadata retrieval error: {str(exc)}",
                )
                raise

    @metadata_cache
    async def get_original_filename(self, key: str) -> Optional[str]:
        """Extracts original filename from metadata."""
        file_info = await self.get_file_info(key)
        return (
            file_info["metadata"].get("x-amz-meta-original-filename")
            if file_info
            else None
        )

    async def get_file_bytes(self, key: str) -> Optional[bytes]:
        """Retrieves file content as bytes."""
        file_object = await self.get_file_object(key)
        if not file_object:
            return None
        streaming_body, _ = file_object
        content = b""
        async for chunk in streaming_body.iter_chunks():
            content += chunk
        return content

    async def log_operation(
        self,
        operation: str,
        details: Optional[str] = None,
        exception: Optional[str] = None,
    ) -> None:
        """Logs storage operations.

        Args:
            operation: Operation name
            details: Operation details
            exception: Error information
        """
        log_data: dict[str, Any] = {
            LogField.TIMESTAMP: datetime.now().isoformat(),
            LogField.OPERATION: operation,
            LogField.DETAILS: details,
            LogField.BUCKET: self.bucket,
            LogField.ENDPOINT: self.endpoint or "AWS default",
        }

        if exception:
            log_data[LogField.EXCEPTION] = exception

        # Add cache information
        log_data["cache_status"] = (
            "invalidated" if "invalidate" in operation else "miss"
        )

        # Log cache size
        try:
            async with redis_client.connection() as r:
                cache_size = await r.dbsize()
                log_data["cache_size"] = cache_size
        except Exception:
            pass

        try:
            self.logger.info(json.dumps(log_data, ensure_ascii=False))
        except Exception:
            self.logger.error("Logging failed", exc_info=True)

    async def check_connection(self) -> bool:
        """Verifies storage connectivity.

        Returns:
            True if connection successful
        """
        try:
            result = await self.check_bucket_exists()
            if not result:
                raise BotoClientError
            return True
        except Exception:
            return False

    async def check_bucket_exists(self) -> bool:
        """Checks if bucket exists.

        Returns:
            True if bucket exists
        """
        async with self._get_client_context() as client:
            try:
                response = await client.list_buckets()
                return any(
                    bucket["Name"] == self.bucket
                    for bucket in response["Buckets"]
                )
            except BotoClientError as exc:
                if exc.response["Error"]["Code"] == "AccessDenied":
                    try:
                        await client.head_bucket(Bucket=self.bucket)
                        return True
                    except BotoClientError:
                        return False
                return False
            except Exception:
                raise

    @metadata_cache
    async def bulk_get_metadata(
        self, keys: list[str]
    ) -> dict[str, Optional[dict]]:
        """Batch retrieves file metadata."""
        async with self._get_client_context() as client:
            results = {}
            for key in keys:
                try:
                    response = await client.head_object(
                        Bucket=self.bucket, Key=key
                    )
                    results[key] = {
                        "last_modified": response["LastModified"],
                        "content_length": response["ContentLength"],
                        "metadata": response.get("Metadata", {}),
                    }
                except BotoClientError:
                    results[key] = None
            return results

    async def _invalidate_cache(self, key: str):
        """Invalidates cache entries for specific key."""
        patterns = [
            f"minio:metadata:*:{self.bucket}:{key}",
            f"minio:exists:*:{self.bucket}:{key}",
        ]

        try:
            async with redis_client.connection() as r:
                async with r.pipeline() as pipe:
                    for pattern in patterns:
                        keys = await r.keys(pattern)
                        if keys:
                            pipe.delete(*keys)
                    await pipe.execute()
        except Exception as exc:
            await self.log_operation(
                operation="cache_invalidation",
                details=f"Key: {key}",
                exception=f"Cache invalidation error: {str(exc)}",
            )

    async def bulk_cache_invalidation(self, keys: list[str]):
        """Performs bulk cache invalidation."""
        try:
            async with redis_client.connection() as r:
                async with r.pipeline() as pipe:
                    for key in keys:
                        patterns = [
                            f"minio:metadata:*:{self.bucket}:{key}",
                            f"minio:exists:*:{self.bucket}:{key}",
                        ]
                        for pattern in patterns:
                            pipe.eval(
                                "local keys = redis.call('keys', ARGV[1]) "
                                "if #keys > 0 then "
                                "return redis.call('del', unpack(keys)) "
                                "else return 0 end",
                                0,
                                pattern,
                            )
                    await pipe.execute()
        except Exception as exc:
            await self.log_operation(
                operation="bulk_cache_invalidation",
                details=f"Keys: {keys}",
                exception=f"Bulk invalidation error: {str(exc)}",
            )


def s3_bucket_service_factory() -> MinioService:
    """Factory function for creating S3 service instance.

    Returns:
        Configured S3 service instance
    """
    return MinioService(settings=settings.storage)
