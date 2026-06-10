"""S56 W3 — base.py part of s3_pool decomp.

Classes: BaseS3Client.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from asyncio import Lock
from collections.abc import AsyncGenerator, Callable, Coroutine
from contextlib import AsyncExitStack, asynccontextmanager
from functools import wraps
from typing import Any, ParamSpec, TypeVar

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


from functools import lru_cache

from src.backend.core.config.settings import FileStorageSettings, settings
from src.backend.core.errors import ServiceError



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
    async def client_context(self) -> AsyncGenerator[Any]:
        """Контекстный менеджер для операций с клиентом."""
        pass

    @abstractmethod
    async def put_object(
        self, key: str, body: Any, metadata: dict[str, Any]
    ) -> dict[str, Any]:
        """Загружает объект в S3."""
        pass

    @abstractmethod
    async def get_object(self, key: str) -> tuple[Any, dict[str, Any]] | None:
        """Получает объект из S3."""
        pass

    @abstractmethod
    async def delete_object(self, key: str) -> dict[str, Any]:
        """Удаляет объект из S3."""
        pass

    @abstractmethod
    async def list_objects(self, prefix: str = None) -> list[str]:
        """Возвращает список объектов в бакете."""
        pass

    @abstractmethod
    async def head_object(self, key: str) -> dict[str, Any] | None:
        """Получает метаданные объекта."""
        pass

    @abstractmethod
    async def create_bucket_if_not_exists(self):
        """Создает бакет, если он не существует."""
        pass

    @abstractmethod
    async def copy_object(self, source_key: str, dest_key: str) -> dict[str, Any]:
        """Копирует объект внутри S3."""
        pass

    @abstractmethod
    async def generate_presigned_url(self, key: str, expiration: int = 3600) -> str:
        """Генерирует предварительно подписанный URL для доступа к объекту."""
        pass

    @abstractmethod
    async def delete_objects(self, keys: list[str]) -> dict[str, Any]:
        """Удаляет несколько объектов одновременно."""
        pass

    @abstractmethod
    async def get_object_bytes(self, key: str) -> bytes | None:
        """Получает содержимое объекта в виде байтов."""
        pass



