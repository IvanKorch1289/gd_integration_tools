from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from fastapi.responses import StreamingResponse

from src.infrastructure.clients.storage.s3_pool import BaseS3Client, s3_client
from src.infrastructure.decorators.caching import existence_cache, metadata_cache
from src.utilities.utils import utilities

__all__ = ("S3Service", "get_s3_service", "get_s3_service_dependency")


class S3Service:
    """Сервис для работы с объектным хранилищем S3."""

    def __init__(self, client: BaseS3Client):
        from src.infrastructure.external_apis.logging_service import fs_logger

        self.client = client
        self.logger = fs_logger
        self._cache_handlers = {
            "metadata": metadata_cache,
            "existence": existence_cache,
        }

    async def upload_file(
        self,
        key: str,
        content: bytes,
        original_filename: str,
        content_type: str | None = None,
        extra_metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        metadata: dict[str, str] = {"original-filename": original_filename}

        if content_type:
            metadata["content-type"] = content_type

        if extra_metadata:
            metadata.update(
                {
                    str(meta_key): str(meta_value)
                    for meta_key, meta_value in extra_metadata.items()
                    if meta_value is not None
                }
            )

        encoded_metadata = await utilities.encode_base64(metadata)

        result = await self.client.put_object(
            key=key, body=content, metadata=encoded_metadata
        )
        await self._invalidate_key_cache(key)
        return result

    async def download_file(self, key: str) -> StreamingResponse:
        result = await self.client.get_object(key)
        if result is None:
            raise FileNotFoundError(f"Файл {key} не найден")

        body, metadata = result
        decoded_metadata = await utilities.decode_base64(metadata)

        filename = decoded_metadata.get("original-filename", key)
        content_type = decoded_metadata.get("content-type", "application/octet-stream")

        async def stream_generator():
            async with body as stream:
                while chunk := await stream.read(64 * 1024):
                    yield chunk

        return StreamingResponse(
            stream_generator(),
            media_type=content_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    async def get_file_bytes(self, key: str) -> bytes:
        content = await self.client.get_object_bytes(key)
        if content is None:
            raise FileNotFoundError(f"Файл {key} не найден")
        return content

    async def multi_upload(self, files: dict[str, bytes]) -> dict[str, Any]:
        results = {}
        for key, content in files.items():
            try:
                await self.client.put_object(key=key, body=content, metadata={})
                await self._invalidate_key_cache(key)
                results[key] = "success"
            except Exception as exc:
                results[key] = str(exc)
        return results

    async def delete_file_object(self, key: str) -> dict[str, Any]:
        result = await self.client.delete_object(key)
        await self._invalidate_key_cache(key)
        return result

    async def create_zip_archive(self, keys: list[str]) -> StreamingResponse:
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
            headers={"Content-Disposition": 'attachment; filename="archive.zip"'},
        )

    async def generate_download_url(self, key: str, expires: int = 3600) -> str:
        return await self.client.generate_presigned_url(key, expires)

    async def get_file_base64(self, key: str) -> str:
        content = await self.client.get_object_bytes(key)
        if content is None:
            raise FileNotFoundError(f"Файл {key} не найден")
        return await utilities.encode_base64(content)

    async def list_files(self, prefix: str = None) -> list[str]:
        return await self.client.list_objects(prefix)

    @metadata_cache
    async def get_file_metadata(self, key: str) -> dict[str, Any]:
        metadata = await self.client.head_object(key)
        if metadata is None:
            raise FileNotFoundError(f"Файл {key} не найден")
        return metadata

    @existence_cache
    async def _check_object_exists(self, key: str) -> bool:
        return (await self.client.head_object(key)) is not None

    @metadata_cache
    async def get_original_filename(self, key: str) -> str | None:
        metadata = await self.client.head_object(key)
        if not metadata:
            return None

        decoded_metadata = await utilities.decode_base64(metadata)
        return decoded_metadata.get("original-filename")

    @metadata_cache
    async def get_content_type(self, key: str) -> str | None:
        metadata = await self.client.head_object(key)
        if not metadata:
            return None

        decoded_metadata = await utilities.decode_base64(metadata)
        return decoded_metadata.get("content-type")

    async def _invalidate_key_cache(self, key: str):
        for cache in self._cache_handlers.values():
            await cache.invalidate(key)
        self.logger.debug(f"Кэш инвалидирован для ключа: {key}")

    async def invalidate_cache(self, key: str | None = None):
        if key:
            await self._invalidate_key_cache(key)
        else:
            for cache in self._cache_handlers.values():
                await cache.invalidate_pattern()
            self.logger.info("Полная инвалидация кэша выполнена")


@asynccontextmanager
async def get_s3_service() -> AsyncGenerator[S3Service, None]:
    s3_service = S3Service(client=s3_client)
    try:
        yield s3_service
    finally:
        pass


_s3_service_dependency_instance: S3Service | None = None


def get_s3_service_dependency() -> S3Service:
    global _s3_service_dependency_instance
    if _s3_service_dependency_instance is None:
        _s3_service_dependency_instance = S3Service(client=s3_client)
    return _s3_service_dependency_instance
