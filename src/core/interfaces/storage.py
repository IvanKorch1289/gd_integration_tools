"""ABC ``ObjectStorage`` для объектных хранилищ (S3 / Azure / GCS / MinIO / LocalFS).

Wave 1.1: вынесено из ``core/interfaces.py``.
Wave F.5a: добавлен ``supports_presigned()`` — фабрика и потребители
могут проверить наличие presigned-URL до вызова метода (LocalFS отдаёт
``file://`` URL, который годится только локально; некоторые backend'ы
могут вообще не поддерживать presigned).
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class ObjectStorage(ABC):
    """Абстракция объектного хранилища (S3, Azure Blob, GCS, MinIO)."""

    @abstractmethod
    async def upload(
        self, key: str, data: bytes, content_type: str | None = None
    ) -> str: ...

    @abstractmethod
    async def download(self, key: str) -> bytes: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    @abstractmethod
    async def exists(self, key: str) -> bool: ...

    @abstractmethod
    async def list_keys(self, prefix: str = "") -> list[str]: ...

    @abstractmethod
    async def presigned_url(self, key: str, expires_in: int = 3600) -> str: ...

    def supports_presigned(self) -> bool:
        """Поддерживает ли backend presigned-URL для прямой клиентской загрузки.

        Default — ``True`` (S3/MinIO/GCS/Azure поддерживают, LocalFS даёт
        ``file://`` — годится локально). Backend'ы без поддержки могут
        вернуть ``False`` и заставить вызывающего использовать
        ``download(key)`` через сервис.
        """
        return True
