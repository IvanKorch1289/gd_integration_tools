"""Протокол S3-сервиса для работы с заказами.

Wave 6.2: вынесено в core, чтобы services/core/orders.py зависел только
от Protocol, а не от конкретной реализации
``infrastructure.external_apis.s3.S3Service``.

Контракт описывает только публичные методы, реально используемые
в OrderService (upload/download/zip/base64/url).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

__all__ = ("OrderStorageProtocol",)


@runtime_checkable
class OrderStorageProtocol(Protocol):
    """S3-подобный сервис для работы с файлами заказов."""

    async def upload_file(
        self, key: str, original_filename: str, content: bytes
    ) -> Any:
        """Загружает файл в хранилище."""
        ...

    async def download_file(self, key: str) -> Any:
        """Скачивает файл из хранилища (возвращает streaming response)."""
        ...

    async def create_zip_archive(self, keys: list[str]) -> Any:
        """Создаёт ZIP-архив из набора ключей."""
        ...

    async def get_file_base64(self, key: str) -> str:
        """Возвращает содержимое файла в формате Base64."""
        ...

    async def generate_download_url(self, key: str, expires: int = 3600) -> str:
        """Генерирует pre-signed URL для скачивания."""
        ...
