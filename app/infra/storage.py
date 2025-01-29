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
from app.utils import singleton
from app.utils.logging import fs_logger


__all__ = (
    "MinioService",
    "BaseS3Service",
    "s3_bucket_service_factory",
)


class LogField:
    """Класс для хранения констант, используемых в логах."""

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
    async def get_file_object(self, key: str) -> Optional[Tuple[StreamingBody, dict]]:
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


@singleton
class MinioService(BaseS3Service):
    """Класс для взаимодействия с сервисом хранения объектов Minio.

    Предоставляет методы для загрузки, получения, удаления и листинга объектов в Minio,
    а также для генерации временных ссылок для скачивания файлов.
    """

    def __init__(self, settings: FileStorageSettings):
        self.settings = settings
        self._initialize_attributes()

    def _initialize_attributes(self):
        """Инициализирует атрибуты из настроек"""
        self.bucket = self.settings.fs_bucket
        self.access_key = self.settings.fs_access_key
        self.secret_key = self.settings.fs_secret_key
        self.endpoint = self._get_endpoint()
        self.client_config = AioConfig(
            connect_timeout=self.settings.fs_timeout,
            retries={"max_attempts": self.settings.fs_retries},
            s3={
                "addressing_style": self._get_addressing_style(),
                "payload_signing_enabled": self.settings.fs_provider == "aws",
            },
        )

    def _get_endpoint(self) -> Optional[str]:
        """Возвращает endpoint из настроек или None для AWS"""
        return self.settings.fs_endpoint if self.settings.fs_provider != "aws" else None

    def _get_addressing_style(self) -> str:
        """Возвращает стиль адресации из настроек"""
        return getattr(self.settings, "fs_addressing_style", "path")

    @asynccontextmanager
    async def _create_s3_client(self) -> AsyncGenerator:
        """Создает контекстный менеджер для работы с клиентом S3.

        Yields:
            AsyncGenerator: Клиент S3.
        """
        session = get_session()
        async with session.create_client(
            "s3",
            endpoint_url=self.endpoint,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            config=self.client_config,
        ) as client:
            yield client

    async def upload_file_object(
        self, key: str, original_filename: str, content: Union[str, bytes]
    ) -> dict:
        """Загружает файл в S3.

        Args:
            key (str): Ключ объекта в S3.
            original_filename (str): Исходное имя файла.
            content (Union[str, bytes]): Содержимое файла (строка или байты).

        Returns:
            dict: Словарь с результатом операции.
        """
        if not content:
            await self.log_operation(
                operation="upload_file_object",
                details=f"Key: {key}, OriginalFilename: {original_filename}",
                exception="Error: File content is empty",
            )
            return {
                "status": "error",
                "message": "File not uploaded",
                "error": "File content is empty",
            }

        buffer = BytesIO(
            content if isinstance(content, bytes) else content.encode("utf-8")
        )

        async with self._create_s3_client() as client:
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
                await self.log_operation(
                    operation="upload_file_object",
                    details=f"Key: {key}, OriginalFilename: {original_filename}, ContentLength: {len(buffer.getvalue())}",
                )
                return {"status": "success", "message": "File upload successful"}
            except Exception as exc:
                await self.log_operation(
                    operation="upload_file_object",
                    details=f"Key: {key}",
                    exception=f"Error: {str(exc)}",
                )
                return {
                    "status": "error",
                    "message": "File upload failed",
                    "error": str(exc),
                }

    async def list_objects(self) -> list[str]:
        """Возвращает список всех объектов в бакете.

        Returns:
            list[str]: Список ключей объектов.
        """
        async with self._create_s3_client() as client:
            try:
                response = await client.list_objects_v2(Bucket=self.bucket)
                return [item["Key"] for item in response.get("Contents", [])]
            except BotoClientError as exc:
                if exc.response["Error"]["Code"] == "NoSuchBucket":
                    return []
                raise
            except Exception as exc:
                await self.log_operation(
                    operation="list_objects", exception=f"Error: {str(exc)}"
                )
                raise

    async def get_file_object(self, key: str) -> Optional[tuple[StreamingBody, dict]]:
        """Получает объект из S3.

        Args:
            key (str): Ключ объекта в S3.

        Returns:
            Optional[tuple[StreamingBody, dict]]: Поток тела объекта и метаданные, если объект найден, иначе None.
        """
        async with self._create_s3_client() as client:
            try:
                response = await client.get_object(Bucket=self.bucket, Key=key)
                return response["Body"], response.get("Metadata", {})
            except BotoClientError as exc:
                if exc.response["Error"]["Code"] == "NoSuchKey":
                    return None
                await self.log_operation(
                    operation="get_file_object",
                    details=f"Key: {key}",
                    exception=f"Error: {str(exc)}",
                )
                raise
            except Exception as exc:
                await self.log_operation(
                    operation="get_file_object",
                    details=f"Key: {key}",
                    exception=f"Error: {str(exc)}",
                )
                raise

    async def delete_file_object(self, key: str) -> dict:
        """Удаляет объект из S3.

        Args:
            key (str): Ключ объекта в S3.

        Returns:
            dict: Словарь с результатом операции.
        """
        async with self._create_s3_client() as client:
            try:
                await client.delete_object(Bucket=self.bucket, Key=key)
                await self.log_operation(
                    operation="delete_file_object", details=f"Key: {key}"
                )
                return {"status": "success", "message": "File deleted successfully"}
            except Exception as exc:
                await self.log_operation(
                    operation="delete_file_object",
                    details=f"Key: {key}",
                    exception=f"Error: {str(exc)}",
                )
                return {
                    "status": "error",
                    "message": "File deletion failed",
                    "error": str(exc),
                }

    async def generate_download_url(
        self, key: str, expires_in: int = 3600
    ) -> Optional[str]:
        """Генерирует временную ссылку для скачивания файла из S3.

        Args:
            key (str): Ключ объекта в S3.
            expires_in (int): Время жизни ссылки в секундах (по умолчанию 3600 секунд).

        Returns:
            Optional[str]: Временная ссылка для скачивания файла или None в случае ошибки.
        """
        async with self._create_s3_client() as client:
            try:
                return await client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self.bucket, "Key": key},
                    ExpiresIn=expires_in,
                )
            except Exception as exc:
                await self.log_operation(
                    operation="generate_download_url",
                    details=f"Key: {key}",
                    exception=f"Error: {str(exc)}",
                )
                return None

    async def file_exists(self, key: str) -> bool:
        """Проверяет существование файла в хранилище."""
        async with self._create_s3_client() as client:
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
                    exception=f"Error: {str(exc)}",
                )
                raise

    async def get_file_info(self, key: str) -> Optional[dict]:
        """Возвращает информацию о файле (метаданные, размер, дата изменения)."""
        async with self._create_s3_client() as client:
            try:
                response = await client.head_object(Bucket=self.bucket, Key=key)
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
                    exception=f"Error: {str(exc)}",
                )
                raise

    async def get_original_filename(self, key: str) -> Optional[str]:
        """Возвращает оригинальное имя файла из метаданных."""
        file_info = await self.get_file_info(key)
        return (
            file_info["metadata"].get("x-amz-meta-original-filename")
            if file_info
            else None
        )

    async def get_file_bytes(self, key: str) -> Optional[bytes]:
        """Возвращает содержимое файла в виде байтов."""
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
        """Логирует операцию и её результат.

        Args:
            operation (str): Название операции.
            details (Optional[str]): Дополнительные детали операции.
            exception (Optional[str]): Информация об ошибке.
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

        try:
            fs_logger.info(json.dumps(log_data, ensure_ascii=False))
        except Exception as exc:
            fs_logger.error(f"Failed to log operation: {str(exc)}")

    @classmethod
    async def health_check_s3(cls) -> bool:
        """Проверяет подключение к S3.

        Returns:
            bool: True, если подключение успешно.

        Raises:
            HTTPException: Если подключение к S3 не удалось.
        """
        async with cls._create_s3_client() as client:
            try:
                result = await client.check_bucket_exists()
                if not result:
                    raise BotoClientError(
                        detail="Minio not connected",
                    )
                return True
            except Exception as exc:
                raise BotoClientError(
                    detail=f"Minio not connected: {str(exc)}",
                )

    async def check_bucket_exists(self) -> bool:
        """Проверяет существование бакета в S3.

        Returns:
            bool: True, если бакет существует, иначе False.
        """
        async with self._create_s3_client() as client:
            try:
                response = await client.list_buckets()
                return any(
                    bucket["Name"] == self.bucket for bucket in response["Buckets"]
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


def s3_bucket_service_factory() -> BaseS3Service:
    """Фабрика для создания экземпляра S3Service с настройками из конфигурации.

    Returns:
        S3Service: Экземпляр S3Service.
    """
    return MinioService(settings=settings.storage)
