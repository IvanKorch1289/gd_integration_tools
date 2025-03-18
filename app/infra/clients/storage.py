from abc import ABC, abstractmethod
from asyncio import Lock
from contextlib import asynccontextmanager
from functools import wraps
from typing import (
    Any,
    AsyncGenerator,
    Callable,
    Coroutine,
    List,
    Optional,
    ParamSpec,
    TypeVar,
)

from botocore.exceptions import ClientError as BotoClientError

from app.config.settings import FileStorageSettings, settings
from app.utils.errors import ServiceError


__all__ = (
    "S3Client",
    "s3_client",
)


P = ParamSpec("P")
R = TypeVar("R")


class BaseS3Client(ABC):
    """Абстрактный базовый класс для операций с клиентом S3."""

    @abstractmethod
    async def connect(self):
        """Устанавливает соединение с хранилищем S3."""
        pass

    @abstractmethod
    async def close(self):
        """Закрывает соединение корректно."""
        pass

    @abstractmethod
    def ensure_connected(func):
        """Декоратор для проверки подключения перед вызовом функции."""
        pass

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Проверяет, установлено ли соединение."""
        pass

    @abstractmethod
    @asynccontextmanager
    async def client_context(self) -> AsyncGenerator[Any, None]:
        """Контекстный менеджер для операций с клиентом."""
        pass

    @abstractmethod
    async def put_object(self, key: str, body: Any, metadata: dict) -> dict:
        """Загружает объект в S3."""
        pass

    @abstractmethod
    async def get_object(self, key: str) -> Optional[tuple[Any, dict]]:
        """Получает объект из S3."""
        pass

    @abstractmethod
    async def delete_object(self, key: str) -> dict:
        """Удаляет объект из S3."""
        pass

    @abstractmethod
    async def list_objects(self, prefix: str = None) -> List[str]:
        """Возвращает список объектов в бакете."""
        pass

    @abstractmethod
    async def head_object(self, key: str) -> Optional[dict]:
        """Получает метаданные объекта."""
        pass

    @abstractmethod
    async def create_bucket_if_not_exists(self):
        """Создает бакет, если он не существует."""
        pass

    @abstractmethod
    async def copy_object(self, source_key: str, dest_key: str) -> dict:
        """Копирует объект внутри S3."""
        pass

    @abstractmethod
    async def generate_presigned_url(
        self, key: str, expiration: int = 3600
    ) -> str:
        """Генерирует предварительно подписанный URL для доступа к объекту."""
        pass

    @abstractmethod
    async def delete_objects(self, keys: List[str]) -> dict:
        """Удаляет несколько объектов одновременно."""
        pass

    @abstractmethod
    async def get_object_bytes(self, key: str) -> Optional[bytes]:
        """Получает содержимое объекта в виде байтов."""
        pass


class S3Client(BaseS3Client):
    """Реализация клиента S3 с расширенными функциями."""

    def __init__(self, settings: FileStorageSettings):
        from aiobotocore.config import AioConfig
        from aiobotocore.session import get_session

        from app.utils.logging_service import fs_logger

        self._connect_lock = Lock()  # Блокировка для безопасного подключения
        self._settings = settings
        self._session = get_session()
        self._client = None
        self.logger = fs_logger
        self._config = AioConfig(
            connect_timeout=settings.timeout,
            read_timeout=settings.read_timeout,
            retries={
                "max_attempts": settings.retries
                or 3,  # 3 попытки по умолчанию
                "mode": "adaptive",  # Экспоненциальный backoff
            },
            max_pool_connections=settings.max_pool_connections,
            tcp_keepalive=True,
            request_min_compression_size_bytes=1024 * 1024,
            s3={
                "addressing_style": "path",
                "payload_signing_enabled": settings.provider == "aws",
            },
        )

    @property
    def is_connected(self) -> bool:
        """Проверяет, установлено ли соединение с S3."""
        return self._client is not None

    async def connect(self):
        """Устанавливает и поддерживает постоянное соединение с S3."""
        if self.is_connected:
            return
        async with self._connect_lock:
            if self.is_connected:  # Двойная проверка внутри блокировки
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
            self.logger.info("Соединение с S3 установлено")

        except Exception as exc:
            await self.close()
            self.logger.error(f"Ошибка подключения: {str(exc)}", exc_info=True)
            raise

    async def close(self):
        """Корректно закрывает соединение."""
        if self._client:
            try:
                await self._client.close()
                self.logger.info("Соединение с S3 закрыто")
            except Exception as exc:
                self.logger.error(
                    f"Ошибка при закрытии соединения: {str(exc)}",
                    exc_info=True,
                )
            finally:
                self._client = None

    @staticmethod
    def ensure_connected[
        **P, R
    ](func: Callable[P, Coroutine[Any, Any, R]]) -> Callable[
        P, Coroutine[Any, Any, R]
    ]:
        """Декоратор для проверки подключения перед вызовом функции."""

        @wraps(func)
        async def wrapper(
            self: "S3Client", *args: P.args, **kwargs: P.kwargs
        ) -> R:
            if not self.is_connected:
                await self.connect()
            return await func(self, *args, **kwargs)

        return wrapper

    async def check_connection(self) -> bool:
        """Проверяет доступность хранилища.

        Returns:
            True, если соединение успешно.
        """
        try:
            result = await self.check_bucket_exists()
            if not result:
                raise BotoClientError("Ошибка соединения")
            return True
        except Exception:
            return False

    async def check_bucket_exists(self) -> bool:
        """Проверяет, существует ли бакет.

        Returns:
            True, если бакет существует.
        """
        async with self.client_context() as client:
            try:
                response = await client.list_buckets()
                return any(
                    bucket["Name"] == self._settings.bucket
                    for bucket in response["Buckets"]
                )
            except BotoClientError as exc:
                if exc.response["Error"]["Code"] == "AccessDenied":
                    try:
                        await client.head_bucket(Bucket=self._settings.bucket)
                        return True
                    except BotoClientError:
                        return False
                return False
            except Exception as exc:
                raise ConnectionError("Не удалось подключиться к S3") from exc

    @asynccontextmanager
    async def client_context(self) -> AsyncGenerator[Any, None]:
        """Контекстный менеджер для работы с клиентом S3 с автоматическим переподключением."""
        try:
            if not self.is_connected:
                await self.connect()
            yield self._client
        except Exception as exc:
            self.logger.error(f"Ошибка соединения: {str(exc)}", exc_info=True)
            await self.close()
            raise BotoClientError("Ошибка API S3") from exc

    @ensure_connected
    async def create_bucket_if_not_exists(self):
        """Создает бакет, если он не существует."""
        try:
            async with self.client_context() as client:
                await client.head_bucket(Bucket=self._settings.bucket)
                self.logger.info(f"Бакет {self._settings.bucket} создан")
        except BotoClientError as exc:
            if exc.response["Error"]["Code"] == "404":
                await self._create_bucket()
            else:
                raise ServiceError("Ошибка создания бакета") from exc

    @ensure_connected
    async def _create_bucket(self):
        """Создает бакет с настройками из конфигурации."""
        async with self.client_context() as client:
            await client.create_bucket(Bucket=self._settings.bucket)
            self.logger.info(f"Создан бакет: {self._settings.bucket}")

    @ensure_connected
    async def put_object(self, key: str, body: Any, metadata: dict) -> dict:
        """Загружает объект в S3."""
        async with self.client_context() as client:
            try:
                await client.put_object(
                    Bucket=self._settings.bucket,
                    Key=key,
                    Body=body,
                    Metadata=metadata,
                )
                self.logger.info(f"Файл {key} успешно загружен")
                return {"status": "success"}
            except BotoClientError as exc:
                self.logger.error(
                    f"Ошибка при загрузке объекта: {str(exc)}", exc_info=True
                )
                return {"status": "error", "message": str(exc)}

    @ensure_connected
    async def get_object(self, key: str) -> Optional[tuple[Any, dict]]:
        """Получает объект из S3."""
        async with self.client_context() as client:
            try:
                response = await client.get_object(
                    Bucket=self._settings.bucket, Key=key
                )
                return response["Body"], response.get("Metadata", {})
            except BotoClientError as exc:
                self.logger.error(f"Файл с ключом {key} не найден")
                if exc.response["Error"]["Code"] == "NoSuchKey":
                    return None
                raise ServiceError("Ошибка при поиске файла") from exc

    @ensure_connected
    async def copy_object(self, source_key: str, dest_key: str) -> dict:
        """Копирует объект внутри одного бакета."""
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
                self.logger.error(
                    f"Ошибка при копировании объекта: {str(exc)}",
                    exc_info=True,
                )
                return {"status": "error", "message": str(exc)}

    @ensure_connected
    async def generate_presigned_url(
        self, key: str, expiration: int = 3600
    ) -> str:
        """Генерирует предварительно подписанный URL для временного доступа."""
        async with self.client_context() as client:
            try:
                url = await client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self._settings.bucket, "Key": key},
                    ExpiresIn=expiration,
                )
                return url
            except Exception as exc:
                self.logger.error(
                    f"Ошибка генерации предварительно подписанного URL: {str(exc)}",
                    exc_info=True,
                )
                raise BotoClientError(
                    "Ошибка генерации предварительно подписанного URL"
                ) from exc

    @ensure_connected
    async def delete_objects(self, keys: List[str]) -> dict:
        """Удаляет несколько объектов одновременно."""
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
                self.logger.error(
                    f"Ошибка при массовом удалении: {str(exc)}", exc_info=True
                )
                return {"status": "error", "message": str(exc)}

    @ensure_connected
    async def delete_object(self, key: str) -> dict:
        """Удаляет один объект из S3."""
        async with self.client_context() as client:
            try:
                response = await client.delete_object(
                    Bucket=self._settings.bucket, Key=key
                )
                self.logger.info(f"Файл {key} успешно удалён")
                return {"status": "success", "response": response}
            except BotoClientError as exc:
                self.logger.error(
                    f"Ошибка при удалении объекта: {str(exc)}", exc_info=True
                )
                return {"status": "error", "message": str(exc)}

    @ensure_connected
    async def head_object(self, key: str) -> Optional[dict]:
        """Получает метаданные и заголовки объекта."""
        async with self.client_context() as client:
            try:
                response = await client.head_object(
                    Bucket=self._settings.bucket, Key=key
                )
                return response["Metadata"]
            except BotoClientError as exc:
                self.logger.error(f"Файл {key} не найден", exc_info=True)
                if exc.response["Error"]["Code"] == "404":
                    return None
                raise ServiceError(f"Файл {key} не найден") from exc

    @ensure_connected
    async def list_objects(self, prefix: str = None) -> List[str]:
        """Возвращает список объектов в бакете с опциональным префиксом."""
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
            except BotoClientError as exc:
                self.logger.error(
                    f"Ошибка при получении списка объектов: {str(exc)}",
                    exc_info=True,
                )
                return []

    @ensure_connected
    async def get_object_bytes(self, key: str) -> Optional[bytes]:
        """Получает содержимое объекта в виде байтов."""
        async with self.client_context() as client:
            try:
                response = await client.get_object(
                    Bucket=self._settings.bucket, Key=key
                )
                return await response["Body"].read()
            except BotoClientError as exc:
                self.logger.error(f"Файл {key} не найден", exc_info=True)
                if exc.response["Error"]["Code"] == "NoSuchKey":
                    return None
                raise ServiceError(f"Файл {key} не найден") from exc


# Экземпляр клиента для работы с S3
s3_client = S3Client(settings=settings.storage)
