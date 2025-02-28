from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

from fastapi.responses import StreamingResponse

from app.infra.clients.storage import BaseS3Client, s3_client
from app.utils.decorators.caching import existence_cache, metadata_cache
from app.utils.decorators.singleton import singleton
from app.utils.utils import utilities


__all__ = ("S3Service", "get_s3_service", "get_s3_service_dependency")


@singleton
class S3Service:
    """Сервис для работы с объектным хранилищем S3."""

    def __init__(self, client: BaseS3Client):
        from app.utils.logging_service import fs_logger

        self.client = client
        self.logger = fs_logger
        self._cache_handlers = {
            "metadata": metadata_cache,
            "existence": existence_cache,
        }

    async def upload_file(
        self, key: str, content: bytes, original_filename: str
    ) -> dict:
        """
        Загружает файл в S3 с метаданными.

        Аргументы:
            key: Уникальный идентификатор файла
            content: Содержимое файла в байтах
            original_filename: Оригинальное имя файла для метаданных

        Возвращает:
            Результат операции загрузки
        """
        metadata = {"original-filename": original_filename}
        encoded_metadata = await utilities.encode_base64(metadata)

        return await self.client.put_object(
            key=key, body=content, metadata=encoded_metadata
        )

    async def download_file(self, key: str) -> StreamingResponse:
        """
        Скачивает файл как потоковый ответ.

        Аргументы:
            key: Идентификатор файла в S3

        Возвращает:
            StreamingResponse с содержимым файла

        Исключения:
            FileNotFoundError: Если файл не найден
        """
        if not await self._check_object_exists(key):
            raise FileNotFoundError(f"Файл {key} не найден")

        result: Optional[tuple[Any, dict]] = await self.client.get_object(key)
        body, metadata = result  # type: ignore
        metadata = await utilities.decode_base64(metadata)
        filename = metadata.get("original-filename", key)

        async def stream_generator():
            async for chunk in body.iter_chunks():
                yield chunk

        return StreamingResponse(
            stream_generator(),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            },
        )

    async def multi_upload(self, files: Dict[str, bytes]) -> dict:
        """
        Параллельная загрузка нескольких файлов.

        Аргументы:
            files: Словарь {ключ_файла: содержимое}

        Возвращает:
            Результаты операций с статусами успеха/ошибки
        """
        results = {}
        for key, content in files.items():
            try:
                await self.client.put_object(
                    key=key, body=content, metadata={}
                )
                await self._invalidate_key_cache(key)
                results[key] = "success"
            except Exception as exc:
                results[key] = str(exc)
        return results

    async def delete_file_object(self, key: list) -> dict:
        """Удаляет объект из хранилища."""
        result = await self.client.delete_object(key)
        await self._invalidate_key_cache(key)
        return result

    async def create_zip_archive(self, keys: List[str]) -> StreamingResponse:
        """
        Создает ZIP-архив из нескольких файлов.

        Аргументы:
            keys: Список идентификаторов файлов

        Возвращает:
            StreamingResponse с ZIP-архивом
        """
        from io import BytesIO
        from zipfile import ZIP_DEFLATED, ZipFile

        buffer = BytesIO()

        with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
            for key in keys:
                if await self._check_object_exists(key):
                    content = await self.client.get_object_bytes(key)
                    filename = await self.get_original_filename(key) or key
                    archive.writestr(filename, content)

        buffer.seek(0)

        return StreamingResponse(
            iter([buffer.getvalue()]),
            media_type="application/zip",
            headers={
                "Content-Disposition": "attachment; filename=archive.zip"
            },
        )

    async def generate_download_url(
        self, key: str, expires: int = 3600
    ) -> str:
        """
        Генерирует временную ссылку для скачивания.

        Аргументы:
            key: Идентификатор файла
            expires: Время жизни ссылки в секундах

        Возвращает:
            Временную URL-ссылку для доступа
        """
        return await self.client.generate_presigned_url(key, expires)

    async def get_file_base64(self, key: str) -> str:
        """
        Получает содержимое файла в base64.

        Аргументы:
            key: Идентификатор файла

        Возвращает:
            Строку в формате base64

        Исключения:
            FileNotFoundError: Если файл не найден
        """
        content = await self.client.get_object_bytes(key)
        if not content:
            raise FileNotFoundError(f"Файл {key} не найден")
        return await utilities.encode_base64(content)

    async def list_files(self, prefix: str = None) -> List[str]:
        """
        Возвращает список файлов в хранилище.

        Аргументы:
            prefix: Фильтр по префиксу имен

        Возвращает:
            Список идентификаторов файлов
        """
        return await self.client.list_objects(prefix)

    @metadata_cache
    async def get_file_metadata(self, key: str) -> dict:
        """Получает метаданные файла с кэшированием."""
        metadata = await self.client.head_object(key)
        return metadata or {}

    @existence_cache
    async def _check_object_exists(self, key: str) -> bool:
        """Проверяет существование файла с кэшированием."""
        metadata = await self.client.head_object(key)
        return metadata is not None

    @metadata_cache
    async def get_original_filename(self, key: str) -> Optional[str]:
        """
        Получает оригинальное имя файла из метаданных.

        Аргументы:
            key: Идентификатор файла

        Возвращает:
            Оригинальное имя файла или None
        """
        metadata = await self.client.head_object(key)
        if not metadata:
            return None

        decoded_metadata = await utilities.decode_base64(metadata)
        return decoded_metadata.get("original-filename")

    async def _invalidate_key_cache(self, key: str):
        """Инвалидирует кэш для конкретного ключа."""
        for cache in self._cache_handlers.values():
            await cache.invalidate(key)
        self.logger.debug(f"Кэш инвалидирован для ключа: {key}")

    async def invalidate_cache(self, key: Optional[str] = None):
        """Публичный метод инвалидации кэша."""
        if key:
            await self._invalidate_key_cache(key)
        else:
            for cache in self._cache_handlers.values():
                await cache.invalidate_pattern()
            self.logger.info("Полная инвалидация кэша выполнена")


@asynccontextmanager
async def get_s3_service() -> AsyncGenerator[S3Service, None]:
    """Фабрика для создания экземпляра S3Service с управлением контекстом."""
    s3_service = S3Service(client=s3_client)
    try:
        yield s3_service
    finally:
        # Логика закрытия соединений при необходимости
        pass


def get_s3_service_dependency() -> Union[S3Service, None]:
    """Возвращает экземпляр S3Service для зависимостей."""
    return S3Service(client=s3_client)
