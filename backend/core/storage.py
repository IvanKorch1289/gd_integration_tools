import json
import traceback
from contextlib import asynccontextmanager
from datetime import datetime
from io import BytesIO
from typing import Any, AsyncGenerator, Optional, Union

from aiobotocore.response import StreamingBody
from aiobotocore.session import get_session
from aiohttp import ClientError

from backend.core.logging_config import fs_logger
from backend.core.settings import settings
from backend.core.utils import singleton


class LogField:
    """Класс для хранения констант, используемых в логах."""

    TIMESTAMP = "timestamp"
    OPERATION = "operation"
    DETAILS = "details"
    BUCKET = "bucket"
    ENDPOINT = "endpoint"
    EXCEPTION = "exception"


@singleton
class S3Service:
    """Класс для взаимодействия с сервисом хранения объектов S3.

    Предоставляет методы для загрузки, получения, удаления и листинга объектов в S3,
    а также для генерации временных ссылок для скачивания файлов.
    """

    def __init__(
        self,
        bucket_name: str,
        endpoint: str,
        access_key: str,
        secret_key: str,
    ):
        """Инициализирует объект сервиса S3.

        Args:
            bucket_name (str): Имя бакета в S3.
            endpoint (str): URL конечной точки S3.
            access_key (str): Доступный ключ для авторизации в S3.
            secret_key (str): Секретный ключ для авторизации в S3.
        """
        self.bucket_name = bucket_name
        self.endpoint = endpoint
        self.access_key = access_key
        self.secret_key = secret_key

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
        # Проверка на пустой файл
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

        # Преобразуем содержимое в BytesIO для проверки на вирусы
        buffer = BytesIO(
            content if isinstance(content, bytes) else content.encode("utf-8")
        )

        # Если файл чист, продолжаем загрузку
        async with self._create_s3_client() as client:
            buffer.seek(0)  # Сбрасываем позицию чтения файла
            metadata = {"x-amz-meta-original-filename": original_filename}
            try:
                await client.put_object(
                    Bucket=self.bucket_name, Key=key, Body=buffer, Metadata=metadata
                )
                await self.log_operation(
                    operation="upload_file_object",
                    details=f"Key: {key}, OriginalFilename: {original_filename}, ContentLength: {len(buffer.getvalue())}",
                )
                return {"status": "success", "message": "File upload successful"}
            except Exception as exc:
                await self.log_operation(
                    operation="upload_file_object", exception=f"Error: {exc}"
                )
                raise  # Исключение будет обработано глобальным обработчиком

    async def list_objects(self) -> list[str]:
        """Возвращает список всех объектов в бакете.

        Returns:
            list[str]: Список ключей объектов.
        """
        async with self._create_s3_client() as client:
            response = await client.list_objects_v2(Bucket=self.bucket_name)
            storage_content: list[str] = []

            try:
                contents = response["Contents"]
            except KeyError:
                raise  # Исключение будет обработано глобальным обработчиком

            for item in contents:
                storage_content.append(item["Key"])

            return storage_content

    async def get_file_object(self, key: str) -> Optional[tuple[StreamingBody, dict]]:
        """Получает объект из S3.

        Args:
            key (str): Ключ объекта в S3.

        Returns:
            Optional[tuple[StreamingBody, dict]]: Поток тела объекта и метаданные, если объект найден, иначе None.
        """
        async with self._create_s3_client() as client:
            try:
                file_obj = await client.get_object(Bucket=self.bucket_name, Key=key)
                body = file_obj.get("Body")
                metadata = file_obj.get("Metadata", {})
                return body, metadata
            except ClientError as exc:
                if exc.response["Error"]["Code"] == "NoSuchKey":
                    return None
                raise  # Исключение будет обработано глобальным обработчиком

    async def delete_file_object(self, key: str) -> dict:
        """Удаляет объект из S3.

        Args:
            key (str): Ключ объекта в S3.

        Returns:
            dict: Словарь с результатом операции.
        """
        async with self._create_s3_client() as client:
            try:
                await client.delete_object(Bucket=self.bucket_name, Key=key)
                await self.log_operation(
                    operation="delete_file_object", details="success"
                )
                return {"status": "success", "message": "File deleted successfully"}
            except Exception as ex:
                await self.log_operation(
                    operation="delete_file_object", exception=f"Error: {ex}"
                )
                return {
                    "status": "error",
                    "message": "File deletion failed",
                    "error": str(ex),
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
                url = await client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self.bucket_name, "Key": key},
                    ExpiresIn=expires_in,
                )
                return url
            except ClientError as exc:
                await self.log_operation(
                    operation="generate_download_url", exception=f"Error: {exc}"
                )
                raise  # Исключение будет обработано глобальным обработчиком

    async def log_operation(
        self,
        operation: str,
        details: Optional[str] = None,
        exception: Optional[Exception] = None,
    ) -> None:
        """Логирует операцию и её результат.

        Args:
            operation (str): Название операции.
            details (Optional[str]): Дополнительные детали операции.
            exception (Optional[Exception]): Исключение, возникшее при выполнении операции.
        """
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
            raise  # Исключение будет обработано глобальным обработчиком

    async def check_bucket_exists(self) -> bool:
        """Проверяет существование бакета в S3.

        Returns:
            bool: True, если бакет существует, иначе False.
        """
        async with self._create_s3_client() as client:
            try:
                buckets_dict = await client.list_buckets()
                return any(
                    bucket.get("Name", None) == self.bucket_name
                    for bucket in buckets_dict.get("Buckets", [])
                )
            except Exception:
                raise  # Исключение будет обработано глобальным обработчиком


def s3_bucket_service_factory() -> S3Service:
    """Фабрика для создания экземпляра S3Service с настройками из конфигурации.

    Returns:
        S3Service: Экземпляр S3Service.
    """
    return S3Service(
        bucket_name=settings.storage_settings.fs_bucket,
        endpoint=settings.storage_settings.fs_endpoint,
        access_key=settings.storage_settings.fs_access_key,
        secret_key=settings.storage_settings.fs_secret_key,
    )
