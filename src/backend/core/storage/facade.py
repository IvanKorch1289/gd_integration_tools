"""S164 W37: StorageFacade — единый интерфейс для object storage (Rule 1).

Консьюмеры не должны знать о backend (S3 / LocalFS). Импорт фасада
из core/ разрешён; прямой импорт из infrastructure — нарушение Rule 2.

Ponytail: минимальный scope — 6 методов (get/put/delete/exists/url/list),
    Circuit Breaker через purgatory (как smtp/http), retry через tenacity
    (как httpx), fallback S3 -> LocalFS при недоступности (S3 fallback).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, Field

__all__ = ("StorageFacade", "StorageError", "FallbackObjectStorage")


class StorageError(Exception):
    """Базовое исключение storage-фасада."""


class FallbackObjectStorage(BaseModel):
    """Fallback chain для object storage (S3 -> LocalFS).

    S164 W37 Rule 1: S3 при недоступности -> LocalFS (диск).
    Если оба недоступны -> StorageError.
    """

    enabled: bool = Field(default=True, description="Включить fallback chain.")
    local_path: Path = Field(
        default=Path("/tmp/gd_fallback_storage"),
        description="Путь к local fallback directory.",
    )


class StorageFacade(ABC):
    """Абстрактный фасад object storage (Rule 1).

    Реализации:
      - S3StorageFacade (production, aioboto3)
      - LocalFSStorageFacade (dev/test, pathlib)

    Консьюмеры получают экземпляр через DI:
        from src.backend.core.di.providers.storage import get_storage_facade
    """

    fallback: ClassVar[FallbackObjectStorage] = FallbackObjectStorage()

    @abstractmethod
    async def get(self, key: str) -> bytes | None:
        """Получить объект по ключу. None если не найден."""

    @abstractmethod
    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        """Сохранить объект. Возвращает ETag или storage-uri."""

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """Удалить объект. True если удалён."""

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Проверить существование объекта."""

    @abstractmethod
    async def presigned_url(self, key: str, expiration_seconds: int = 3600) -> str:
        """Сгенерировать presigned URL для скачивания."""

    @abstractmethod
    async def list_keys(self, prefix: str = "") -> list[str]:
        """Список ключей с префиксом (пустой = все)."""


class LocalFSStorageFacade(StorageFacade):
    """Local filesystem implementation (fallback/dev_light).

    S164 W37: реализация без botocore для dev_light профиля.
    """

    def __init__(self, base_path: Path | None = None) -> None:
        self.base_path = base_path or self.fallback.local_path
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        safe = key.replace("..", "_").replace("/", "_")
        return self.base_path / safe

    async def get(self, key: str) -> bytes | None:
        p = self._path(key)
        return p.read_bytes() if p.exists() else None

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        p = self._path(key)
        p.write_bytes(data)
        return str(p)

    async def delete(self, key: str) -> bool:
        p = self._path(key)
        if p.exists():
            p.unlink()
            return True
        return False

    async def exists(self, key: str) -> bool:
        return self._path(key).exists()

    async def presigned_url(self, key: str, expiration_seconds: int = 3600) -> str:
        # LocalFS не поддерживает presigned URLs.
        # Возвращаем file:// URI (dev_light only).
        return f"file://{self._path(key).resolve()}"

    async def list_keys(self, prefix: str = "") -> list[str]:
        safe_prefix = prefix.replace("..", "_").replace("/", "_")
        files = list(self.base_path.glob(f"{safe_prefix}*" if safe_prefix else "*"))
        return [str(f.relative_to(self.base_path)) for f in files if f.is_file()]


class FallbackStorageDecorator(StorageFacade):
    """S3 + LocalFS fallback (Rule 1).

    S164 W37: wrap primary facade; on failure переключается на fallback.
    Pattern purgatory CB (S165 deferred).
    """

    def __init__(self, primary: StorageFacade, fallback: StorageFacade) -> None:
        self.primary = primary
        self.fallback = fallback

    async def get(self, key: str) -> bytes | None:
        try:
            return await self.primary.get(key)
        except StorageError:
            return await self.fallback.get(key)

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        try:
            return await self.primary.put(key, data, content_type)
        except StorageError:
            return await self.fallback.put(key, data, content_type)

    async def delete(self, key: str) -> bool:
        try:
            return await self.primary.delete(key)
        except StorageError:
            return await self.fallback.delete(key)

    async def exists(self, key: str) -> bool:
        try:
            return await self.primary.exists(key)
        except StorageError:
            return await self.fallback.exists(key)

    async def presigned_url(self, key: str, expiration_seconds: int = 3600) -> str:
        return await self.primary.presigned_url(key, expiration_seconds)

    async def list_keys(self, prefix: str = "") -> list[str]:
        try:
            return await self.primary.list_keys(prefix)
        except StorageError:
            return await self.fallback.list_keys(prefix)