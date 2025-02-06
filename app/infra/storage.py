# app/infra/storage/s3.py
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from functools import wraps
from typing import Any, AsyncGenerator, List, Optional

from aiobotocore.config import AioConfig
from aiobotocore.session import get_session
from botocore.exceptions import ClientError as BotoClientError

from app.config.services import FileStorageSettings
from app.config.settings import settings
from app.utils.logging_service import fs_logger


__all__ = (
    "S3Client",
    "s3_client",
)


class BaseS3Client(ABC):
    """Abstract base class for S3 client operations."""

    @abstractmethod
    async def connect(self):
        """Establish connection to S3 storage."""
        pass

    @abstractmethod
    async def close(self):
        """Close the connection gracefully."""
        pass

    @abstractmethod
    def ensure_connected(func):
        """Ensure client is connected before calling the decorated function."""
        pass

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Check if client is connected."""
        pass

    @abstractmethod
    @asynccontextmanager
    async def client_context(self) -> AsyncGenerator[Any, None]:
        """Context manager for client operations."""
        pass

    @abstractmethod
    async def put_object(self, key: str, body: Any, metadata: dict) -> dict:
        """Upload object to S3."""
        pass

    @abstractmethod
    async def get_object(self, key: str) -> Optional[tuple[Any, dict]]:
        """Retrieve object from S3."""
        pass

    @abstractmethod
    async def delete_object(self, key: str) -> dict:
        """Delete object from S3."""
        pass

    @abstractmethod
    async def list_objects(self, prefix: str = None) -> List[str]:
        """List objects in bucket."""
        pass

    @abstractmethod
    async def head_object(self, key: str) -> Optional[dict]:
        """Get object metadata."""
        pass

    @abstractmethod
    async def create_bucket_if_not_exists(self):
        """Create bucket if it doesn't exist."""
        pass

    @abstractmethod
    async def copy_object(self, source_key: str, dest_key: str) -> dict:
        """Copy object within S3."""
        pass

    @abstractmethod
    async def generate_presigned_url(
        self, key: str, expiration: int = 3600
    ) -> str:
        """Generate pre-signed URL for object access."""
        pass

    @abstractmethod
    async def delete_objects(self, keys: List[str]) -> dict:
        """Delete multiple objects at once."""
        pass

    @abstractmethod
    async def get_object_bytes(self, key: str) -> Optional[bytes]:
        """Get object content as bytes."""
        pass


class S3Client(BaseS3Client):
    """S3 client implementation with advanced features."""

    def __init__(self, settings: FileStorageSettings):
        self._settings = settings
        self._session = get_session()
        self._client = None
        self.logger = fs_logger
        self._config = AioConfig(
            connect_timeout=settings.timeout,
            retries={"max_attempts": settings.retries},
            s3={
                "addressing_style": "path",
                "payload_signing_enabled": settings.provider == "aws",
            },
        )

    @property
    def is_connected(self) -> bool:
        return self._client is not None

    async def connect(self):
        """Establish and maintain persistent connection to S3."""
        if self.is_connected:
            return

        try:
            self._client = await self._session.create_client(
                service_name="s3",
                endpoint_url=self._settings.endpoint,
                aws_access_key_id=self._settings.access_key,
                aws_secret_access_key=self._settings.secret_key,
                config=self._config,
                use_ssl=self._settings.use_ssl,
            ).__aenter__()

            await self.create_bucket_if_not_exists()
            self.logger.info("S3 connection established")

        except Exception:
            await self.close()
            self.logger.error("Connection failed", exc_info=True)
            raise

    async def close(self):
        """Gracefully close connection."""
        if self._client:
            try:
                await self._client.close()
                self.logger.info("S3 connection closed")
            except Exception:
                self.logger.error("Error closing connection", exc_info=True)
            finally:
                self._client = None

    def ensure_connected(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            if not self.is_connected:
                await self.connect()
            return await func(self, *args, **kwargs)

        return wrapper

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
        async with self.client_context() as client:
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

    @asynccontextmanager
    async def client_context(self) -> AsyncGenerator[Any, None]:
        """Managed context for S3 client with automatic reconnection."""
        try:
            if not self.is_connected:
                await self.connect()
            yield self._client
        except BotoClientError:
            self.logger.error("S3 API error", exc_info=True)
            raise
        except Exception:
            self.logger.error("Connection error", exc_info=True)
            await self.close()
            raise

    @ensure_connected
    async def create_bucket_if_not_exists(self):
        """Ensure bucket exists in storage."""
        try:
            async with self.client_context() as client:
                await client.head_bucket(Bucket=self._settings.bucket)
        except BotoClientError as e:
            if e.response["Error"]["Code"] == "404":
                await self._create_bucket()
            else:
                raise

    @ensure_connected
    async def _create_bucket(self):
        """Create configured bucket with proper settings."""
        async with self.client_context() as client:
            await client.create_bucket(Bucket=self._settings.bucket)
            self.logger.info(f"Created bucket: {self._settings.bucket}")

    @ensure_connected
    async def put_object(self, key: str, body: Any, metadata: dict) -> dict:
        """Low-level put object operation."""
        async with self.client_context() as client:
            try:
                await client.put_object(
                    Bucket=self._settings.bucket,
                    Key=key,
                    Body=body,
                    Metadata=metadata,
                )
                return {"status": "success"}
            except BotoClientError as exc:
                self.logger.error("Put operation failed", exc_info=True)
                return {"status": "error", "message": str(exc)}

    @ensure_connected
    async def get_object(self, key: str) -> Optional[tuple[Any, dict]]:
        """Low-level get object operation."""
        async with self.client_context() as client:
            try:
                response = await client.get_object(
                    Bucket=self._settings.bucket, Key=key
                )
                return response["Body"], response.get("Metadata", {})
            except BotoClientError as exc:
                self.logger.error(f"File with key {key} not found")
                if exc.response["Error"]["Code"] == "NoSuchKey":
                    return None
                raise

    @ensure_connected
    async def copy_object(self, source_key: str, dest_key: str) -> dict:
        """Copy object within the same bucket."""
        copy_source = {"Bucket": self._settings.bucket, "Key": source_key}
        async with self.client_context() as client:
            try:
                await client.copy_object(
                    Bucket=self._settings.bucket,
                    Key=dest_key,
                    CopySource=copy_source,
                )
                return {"status": "success"}
            except BotoClientError as exc:
                self.logger.error("Copy operation failed", exc_info=True)
                return {"status": "error", "message": str(exc)}

    @ensure_connected
    async def generate_presigned_url(
        self, key: str, expiration: int = 3600
    ) -> str:
        """Generate pre-signed URL for temporary access."""
        async with self.client_context() as client:
            try:
                url = await client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self._settings.bucket, "Key": key},
                    ExpiresIn=expiration,
                )
                return url
            except BotoClientError:
                self.logger.error(
                    "Presigned URL generation failed", exc_info=True
                )
                raise

    @ensure_connected
    async def delete_objects(self, keys: List[str]) -> dict:
        """Batch delete objects."""
        async with self.client_context() as client:
            try:
                response = await client.delete_objects(
                    Bucket=self._settings.bucket,
                    Delete={"Objects": [{"Key": key} for key in keys]},
                )
                return {
                    "deleted": [
                        obj["Key"] for obj in response.get("Deleted", [])
                    ],
                    "errors": response.get("Errors", []),
                }
            except BotoClientError as exc:
                self.logger.error("Batch delete failed", exc_info=True)
                return {"status": "error", "message": str(exc)}

    @ensure_connected
    async def delete_object(self, key: str) -> dict:
        """Delete single object from S3."""
        async with self.client_context() as client:
            try:
                response = await client.delete_object(
                    Bucket=self._settings.bucket, Key=key
                )
                return {"status": "success", "response": response}
            except BotoClientError as exc:
                self.logger.error("Delete operation failed", exc_info=True)
                return {"status": "error", "message": str(exc)}

    @ensure_connected
    async def head_object(self, key: str) -> Optional[dict]:
        """Get object metadata and headers."""
        async with self.client_context() as client:
            try:
                response = await client.head_object(
                    Bucket=self._settings.bucket, Key=key
                )

                return response["Metadata"]
            except BotoClientError as exc:
                self.logger.error(f"File {key} not found", exc_info=True)
                if exc.response["Error"]["Code"] == "404":
                    return None
                raise

    @ensure_connected
    async def list_objects(self, prefix: str = None) -> List[str]:
        """List objects in bucket with optional prefix."""
        objects = []
        async with self.client_context() as client:
            try:
                paginator = client.get_paginator("list_objects_v2")
                async for result in paginator.paginate(
                    Bucket=self._settings.bucket,
                    Prefix=prefix or "",
                ):
                    for content in result.get("Contents", []):
                        objects.append(content["Key"])
                return objects
            except BotoClientError:
                self.logger.error("List objects failed", exc_info=True)
                return []

    @ensure_connected
    async def get_object_bytes(self, key: str) -> Optional[bytes]:
        """Get object content as bytes."""
        async with self.client_context() as client:
            try:
                response = await client.get_object(
                    Bucket=self._settings.bucket, Key=key
                )
                return await response["Body"].read()
            except BotoClientError as exc:
                self.logger.error(f"File {key} not found", exc_info=True)
                if exc.response["Error"]["Code"] == "NoSuchKey":
                    return None
                raise


s3_client = S3Client(settings=settings.storage)
