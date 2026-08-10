"""S56 W3 — base.py part of s3_pool decomp.

Classes: BaseS3Client.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, ParamSpec, TypeVar

try:
    from botocore.exceptions import (  # type: ignore[import-not-found]  # noqa: F401 — availability probe
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


P = ParamSpec("P")
R = TypeVar("R")


class BaseS3Client(ABC):
    """Абстрактный базовый класс для операций с клиентом S3."""

    @abstractmethod
    async def connect(self):
        """Устанавливает соединение с хранилищем S3."""

    @abstractmethod
    async def close(self):
        """Закрывает соединение корректно."""

    @abstractmethod
    def ensure_connected(func):
        """Декоратор для проверки подключения перед вызовом функции."""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Проверяет, установлено ли соединение."""

    @abstractmethod
    @asynccontextmanager
    async def client_context(self) -> AsyncGenerator[Any]:
        """Контекстный менеджер для операций с клиентом."""

    @abstractmethod
    async def put_object(
        self, key: str, body: Any, metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """Загружает объект в S3."""

    @abstractmethod
    async def get_object(self, key: str) -> tuple[Any, dict[str, Any]] | None:
        """Получает объект из S3."""

    @abstractmethod
    async def delete_object(self, key: str) -> dict[str, Any]:
        """Удаляет объект из S3."""

    @abstractmethod
    async def list_objects(self, prefix: str | None = None) -> list[str]:
        """Возвращает список объектов в бакете."""

    @abstractmethod
    async def head_object(self, key: str) -> dict[str, Any] | None:
        """Получает метаданные объекта."""

    @abstractmethod
    async def create_bucket_if_not_exists(self):
        """Создает бакет, если он не существует."""

    @abstractmethod
    async def copy_object(self, source_key: str, dest_key: str) -> dict[str, Any]:
        """Копирует объект внутри S3."""

    @abstractmethod
    async def generate_presigned_url(self, key: str, expiration: int = 3600) -> str:
        """Генерирует предварительно подписанный URL для доступа к объекту."""

    @abstractmethod
    async def delete_objects(self, keys: list[str]) -> dict[str, Any]:
        """Удаляет несколько объектов одновременно."""

    @abstractmethod
    async def get_object_bytes(self, key: str) -> bytes | None:
        """Получает содержимое объекта в виде байтов."""
