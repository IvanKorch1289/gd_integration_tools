"""S56 W3 — client.py part of s3_pool decomp.

Classes: S3Client.
"""

from __future__ import annotations

from asyncio import Lock
from collections.abc import AsyncGenerator, Callable, Coroutine
from contextlib import AsyncExitStack, asynccontextmanager
from functools import wraps
from typing import Any, ParamSpec, TypeVar

from src.backend.infrastructure.clients.storage.s3_pool.base import BaseS3Client

try:
    from botocore.exceptions import (  # type: ignore[import-not-found]
        ClientError as BotoClientError,  # type: ignore[import-not-found]  # type: ignore  # type: ignore[unused-ignore]
    )
except ImportError:  # botocore — опциональная зависимость dev_light

    class BotoClientError(Exception):  # type: ignore[no-redef]
        """Stub для случая, когда botocore не установлен (dev_light без S3).

        Принимает произвольные kwargs (``error_response``,
        ``operation_name``) как и реальный ``botocore.exceptions.ClientError``,
        чтобы код, генерирующий исключение в кодпуте без botocore, не падал
        с ``TypeError: takes no keyword arguments``.
        """

        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args)
            self.response = kwargs.get("error_response", {"Error": {"Code": ""}})
            self.operation_name = kwargs.get("operation_name", "")


from src.backend.core.config.settings import FileStorageSettings
from src.backend.core.errors import ServiceError

P = ParamSpec("P")
R = TypeVar("R")


class S3Client(BaseS3Client):
    """Реализация клиента S3 с расширенными функциями."""

    def __init__(self, settings: FileStorageSettings):
        from src.backend.infrastructure.logging.factory import get_logger

        self._connect_lock = Lock()
        self._settings = settings
        self._client = None
        self._exit_stack: AsyncExitStack | None = None
        self.logger = get_logger("storage")
        self._session: Any = None
        self._config: Any = None

        # На dev_light с провайдером ``local`` или ``enabled=false``
        # aiobotocore не нужен — пропускаем тяжёлый импорт. Реальные
        # вызовы S3 защищены через _s3_enabled() guard в setup_infra.py.
        if (
            not getattr(settings, "enabled", True)
            or getattr(settings, "provider", "minio") == "local"
        ):
            return

        # S11 carryover: aiobotocore — optional dependency. На dev-light
        # без extras `[sources-cdc,...]` модуль отсутствует — graceful
        # skip без crash (тесты unrelated до S3 продолжают собираться).
        try:
            from aiobotocore.config import AioConfig
            from aiobotocore.session import get_session
        except ImportError:
            self._session = None
            self._config = None
            return

        self._session = get_session()
        self._config = AioConfig(
            connect_timeout=settings.timeout,
            read_timeout=settings.read_timeout,
            retries={"max_attempts": settings.retries or 3, "mode": "adaptive"},
            max_pool_connections=settings.max_pool_connections,
            tcp_keepalive=True,
            s3={
                "addressing_style": "path",
                "payload_signing_enabled": settings.provider == "aws",
            },
        )

    async def connect(self) -> None:
        if self.is_connected:
            return

        async with self._connect_lock:
            if self.is_connected:
                return

            try:
                exit_stack = AsyncExitStack()
                client = await exit_stack.enter_async_context(
                    self._session.create_client(
                        service_name="s3",
                        endpoint_url=self._settings.endpoint,
                        aws_access_key_id=self._settings.access_key,
                        aws_secret_access_key=self._settings.secret_key,
                        config=self._config,
                        use_ssl=self._settings.use_ssl,
                    )
                )

                self._client = client
                self._exit_stack = exit_stack

                await self.create_bucket_if_not_exists()
                self.logger.info("Соединение с S3 установлено")
            except Exception as exc:
                await self.close()
                self.logger.error(
                    "Ошибка подключения к S3: %s", str(exc), exc_info=True
                )
                raise

    async def close(self) -> None:
        if self._exit_stack is not None:
            try:
                await self._exit_stack.aclose()
                self.logger.info("Соединение с S3 закрыто")
            except Exception as exc:
                self.logger.error(
                    "Ошибка при закрытии соединения S3: %s", str(exc), exc_info=True
                )
            finally:
                self._exit_stack = None
                self._client = None

    @property
    def is_connected(self) -> bool:
        """Проверяет, установлено ли соединение."""
        return self._client is not None and self._exit_stack is not None

    @staticmethod
    def ensure_connected(
        func: Callable[..., Coroutine[Any, Any, Any]],
    ) -> Callable[..., Coroutine[Any, Any, Any]]:
        """Декоратор для проверки подключения перед вызовом функции."""

        @wraps(func)
        async def wrapper(self: "S3Client", *args: Any, **kwargs: Any) -> Any:
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
                raise BotoClientError(
                    error_response={"Error": {"Message": "Ошибка соединения"}},
                    operation_name="checking connection",
                )
            return True
        except (BotoClientError, OSError, TimeoutError):
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
    async def client_context(self) -> AsyncGenerator[Any]:
        """Контекстный менеджер для работы с клиентом S3 с автоматическим переподключением."""
        try:
            if not self.is_connected:
                await self.connect()
            yield self._client
        except Exception as exc:
            self.logger.error(f"Ошибка соединения: {exc!s}", exc_info=True)
            await self.close()
            raise BotoClientError(
                error_response={"Error": {"Message": "Ошибка API S3"}},
                operation_name="Connection",
            ) from exc

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
    async def put_object(
        self, key: str, body: Any, metadata: dict[str, Any]
    ) -> dict[str, Any]:
        """Загружает объект в S3."""
        async with self.client_context() as client:
            try:
                await client.put_object(
                    Bucket=self._settings.bucket, Key=key, Body=body, Metadata=metadata
                )
                self.logger.info(f"Файл {key} успешно загружен")
                return {"status": "success"}
            except BotoClientError as exc:
                self.logger.error(
                    f"Ошибка при загрузке объекта: {exc!s}", exc_info=True
                )
                return {"status": "error", "message": str(exc)}

    @ensure_connected
    async def get_object(self, key: str) -> tuple[Any, dict[str, Any]] | None:
        """Получает объект из S3."""
        async with self.client_context() as client:
            try:
                response = await client.get_object(
                    Bucket=self._settings.bucket, Key=key
                )
                return response["Body"], response.get("Metadata", {})
            except BotoClientError as exc:
                code = str(exc.response.get("Error", {}).get("Code", ""))
                if code in {"404", "NoSuchKey", "NotFound"}:
                    return None
                raise ServiceError(f"Ошибка получения файла {key}") from exc

    @ensure_connected
    async def put_object_multipart(
        self,
        *,
        key: str,
        stream: Any,
        part_size: int = 8 * 1024 * 1024,
        content_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Загружает объект через multipart upload из async-итератора (S13 K2 W1).

        Чанки накапливаются до ``part_size`` (минимум 5MB по S3 API),
        затем отправляются как ``upload_part``. При ошибке выполняется
        ``abort_multipart_upload`` для очистки.

        Args:
            key: Ключ объекта в bucket.
            stream: ``AsyncIterator[bytes]`` — обычно ``request.stream()``.
            part_size: Минимальный размер part'а в байтах (default 8MB).
            content_type: MIME content-type.
            metadata: S3-метаданные.

        Returns:
            ETag загруженного объекта.
        """
        # Минимальный part_size S3 — 5MB (кроме последнего part'а).
        part_size = max(part_size, 5 * 1024 * 1024)
        bucket = self._settings.bucket
        upload_id: str | None = None
        parts: list[dict[str, Any]] = []

        async with self.client_context() as client:
            try:
                create_kwargs: dict[str, Any] = {"Bucket": bucket, "Key": key}
                if content_type:
                    create_kwargs["ContentType"] = content_type
                if metadata:
                    create_kwargs["Metadata"] = metadata
                response = await client.create_multipart_upload(**create_kwargs)
                upload_id = response["UploadId"]

                buffer = bytearray()
                part_number = 1
                async for chunk in stream:
                    if not chunk:
                        continue
                    buffer.extend(chunk)
                    while len(buffer) >= part_size:
                        part_bytes = bytes(buffer[:part_size])
                        del buffer[:part_size]
                        part_resp = await client.upload_part(
                            Bucket=bucket,
                            Key=key,
                            UploadId=upload_id,
                            PartNumber=part_number,
                            Body=part_bytes,
                        )
                        parts.append(
                            {"PartNumber": part_number, "ETag": part_resp["ETag"]}
                        )
                        part_number += 1

                if buffer:
                    part_resp = await client.upload_part(
                        Bucket=bucket,
                        Key=key,
                        UploadId=upload_id,
                        PartNumber=part_number,
                        Body=bytes(buffer),
                    )
                    parts.append({"PartNumber": part_number, "ETag": part_resp["ETag"]})

                if not parts:
                    # Нет данных — S3 не позволит complete; abort и возвращаем "".
                    await client.abort_multipart_upload(
                        Bucket=bucket, Key=key, UploadId=upload_id
                    )
                    return ""

                complete_resp = await client.complete_multipart_upload(
                    Bucket=bucket,
                    Key=key,
                    UploadId=upload_id,
                    MultipartUpload={"Parts": parts},
                )
                return str(complete_resp.get("ETag", ""))
            except Exception as _:
                if upload_id is not None:
                    try:
                        await client.abort_multipart_upload(
                            Bucket=bucket, Key=key, UploadId=upload_id
                        )
                    except Exception as _:
                        self.logger.exception(
                            "s3.multipart_abort_failed key=%s upload_id=%s",
                            key,
                            upload_id,
                        )
                raise

    @ensure_connected
    async def copy_object(self, source_key: str, dest_key: str) -> dict[str, Any]:
        """Копирует объект внутри одного бакета."""
        copy_source = {"Bucket": self._settings.bucket, "Key": source_key}
        async with self.client_context() as client:
            try:
                await client.copy_object(
                    Bucket=self._settings.bucket, Key=dest_key, CopySource=copy_source
                )
                return {"status": "success"}
            except BotoClientError as exc:
                self.logger.error(
                    f"Ошибка при копировании объекта: {exc!s}", exc_info=True
                )
                return {"status": "error", "message": str(exc)}

    @ensure_connected
    async def generate_presigned_url(self, key: str, expiration: int = 3600) -> str:
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
                    f"Ошибка генерации предварительно подписанного URL: {exc!s}",
                    exc_info=True,
                )
                raise BotoClientError(
                    error_response={
                        "Error": {
                            "Message": "Ошибка генерации предварительно подписанного URL"
                        }
                    },
                    operation_name="generating presigned url",
                ) from exc

    @ensure_connected
    async def delete_objects(self, keys: list[str]) -> dict[str, Any]:
        """Удаляет несколько объектов одновременно."""
        async with self.client_context() as client:
            try:
                response = await client.delete_objects(
                    Bucket=self._settings.bucket,
                    Delete={"Objects": [{"Key": key} for key in keys]},
                )
                return {
                    "deleted": [obj["Key"] for obj in response.get("Deleted", [])],
                    "errors": response.get("Errors", []),
                }
            except BotoClientError as exc:
                self.logger.error(
                    f"Ошибка при массовом удалении: {exc!s}", exc_info=True
                )
                return {"status": "error", "message": str(exc)}

    @ensure_connected
    async def delete_object(self, key: str) -> dict[str, Any]:
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
                    f"Ошибка при удалении объекта: {exc!s}", exc_info=True
                )
                return {"status": "error", "message": str(exc)}

    @ensure_connected
    async def head_object(self, key: str) -> dict[str, Any] | None:
        """Получает метаданные и заголовки объекта."""
        async with self.client_context() as client:
            try:
                response = await client.head_object(
                    Bucket=self._settings.bucket, Key=key
                )
                return response.get("Metadata", {})
            except BotoClientError as exc:
                code = str(exc.response.get("Error", {}).get("Code", ""))
                if code in {"404", "NoSuchKey", "NotFound"}:
                    return None

                self.logger.error(
                    "Ошибка head_object для %s: %s", key, str(exc), exc_info=True
                )
                raise ServiceError(f"Ошибка получения метаданных {key}") from exc

    @ensure_connected
    async def list_objects(self, prefix: str = None) -> list[str]:
        """Возвращает список объектов в бакете с опциональным префиксом."""
        objects = []
        async with self.client_context() as client:
            try:
                paginator = client.get_paginator("list_objects_v2")
                async for result in paginator.paginate(
                    Bucket=self._settings.bucket, Prefix=prefix or ""
                ):
                    for content in result.get("Contents", []):
                        objects.append(content["Key"])
                return objects
            except BotoClientError as exc:
                self.logger.error(
                    f"Ошибка при получении списка объектов: {exc!s}", exc_info=True
                )
                return []

    @ensure_connected
    async def get_object_bytes(self, key: str) -> bytes | None:
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
