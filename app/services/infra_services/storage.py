import io
import zipfile
from typing import Dict, List, Optional

import base64
from fastapi.responses import StreamingResponse

from app.infra.storage import BaseS3Client, s3_client
from app.utils.decorators.caching import existence_cache, metadata_cache
from app.utils.logging_service import fs_logger


__all__ = (
    "S3Service",
    "get_s3_service",
)


class S3Service:
    """Service layer for high-level file operations with S3."""

    def __init__(self, client: BaseS3Client):
        self.client = client
        self.logger = fs_logger
        self._cache_handlers = {
            "metadata": metadata_cache,
            "existence": existence_cache,
        }

    async def _encode_metadata(self, metadata: dict) -> dict:
        """Encode non-ASCII metadata values to be ASCII-compatible."""
        encoded_metadata = {}
        for key, value in metadata.items():
            if isinstance(value, str):
                encoded_value = base64.b64encode(value.encode("utf-8")).decode(
                    "ascii"
                )
                encoded_metadata[key] = encoded_value
            else:
                encoded_metadata[key] = value
        return encoded_metadata

    async def _decode_metadata(self, metadata: dict) -> dict:
        """Decode URL-encoded metadata values back to original strings."""
        decoded_metadata = {}
        for key, value in metadata.items():
            if isinstance(value, str):
                try:
                    decoded_value = base64.b64decode(value).decode("utf-8")
                    decoded_metadata[key] = decoded_value
                except (UnicodeDecodeError, ValueError):
                    decoded_metadata[key] = value
            else:
                decoded_metadata[key] = value
        return decoded_metadata

    async def upload_file(
        self, key: str, content: bytes, original_filename: str
    ) -> dict:
        """
        Upload a file to S3 with metadata.

        Args:
            key: Unique file identifier in S3
            content: File content as bytes
            original_filename: Original filename for metadata

        Returns:
            Upload operation result
        """
        metadata = {"original-filename": original_filename}
        encoded_metadata = await self._encode_metadata(metadata)

        return await self.client.put_object(
            key=key, body=content, metadata=encoded_metadata
        )

    async def download_file(self, key: str) -> StreamingResponse:
        """
        Download file as streaming response.

        Args:
            key: File identifier in S3

        Returns:
            FastAPI StreamingResponse with file content
        """
        if not await self._check_object_exists(key):
            raise FileNotFoundError(f"File {key} not found")

        result = await self.client.get_object(key)
        body, metadata = result
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
        Upload multiple files in parallel.

        Args:
            files: Dictionary of {file_key: content}

        Returns:
            Upload results with success/failure status
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
        """Deletes an object from storage."""
        result = await self.client.delete_object(key)
        await self._invalidate_key_cache(key)
        return result

    async def create_zip_archive(self, keys: List[str]) -> StreamingResponse:
        """
        Create ZIP archive from multiple files.

        Args:
            keys: List of file keys to include

        Returns:
            StreamingResponse with ZIP archive
        """
        buffer = io.BytesIO()

        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
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
        Generate temporary download URL.

        Args:
            key: File identifier in S3
            expires: URL expiration time in seconds

        Returns:
            Pre-signed download URL
        """
        return await self.client.generate_presigned_url(key, expires)

    async def get_file_base64(self, key: str) -> str:
        """
        Get file content as base64 encoded string.

        Args:
            key: File identifier in S3

        Returns:
            Base64 encoded file content
        """
        content = await self.client.get_object_bytes(key)
        if not content:
            raise FileNotFoundError(f"File {key} not found")
        return base64.b64encode(content).decode("utf-8")

    async def list_files(self, prefix: str = None) -> List[str]:
        """
        List files in bucket with optional prefix filter.

        Args:
            prefix: Prefix filter for file keys

        Returns:
            List of file keys
        """
        return await self.client.list_objects(prefix)

    @metadata_cache
    async def get_file_metadata(self, key: str) -> dict:
        """Get full metadata with caching"""
        metadata = await self.client.head_object(key)
        return metadata or {}

    @existence_cache
    async def _check_object_exists(self, key: str) -> bool:
        """Cached existence check with metadata refresh"""
        metadata = await self.client.head_object(key)
        return metadata is not None

    @metadata_cache
    async def get_original_filename(self, key: str) -> Optional[str]:
        """
        Retrieve original filename from metadata.

        Args:
            key: File identifier in S3

        Returns:
            Original filename if exists
        """
        metadata = await self.client.head_object(key)
        if not metadata:
            return None

        decoded_metadata = await self._decode_metadata(metadata)
        return decoded_metadata.get("original-filename")

    async def _invalidate_key_cache(self, key: str):
        """Invalidate all cache entries for specific key"""
        for cache in self._cache_handlers.values():
            await cache.invalidate(key)
        self.logger.debug(f"Cache invalidated for key: {key}")

    async def invalidate_cache(self, key: Optional[str] = None):
        """Public cache invalidation method"""
        if key:
            await self._invalidate_key_cache(key)
        else:
            for cache in self._cache_handlers.values():
                await cache.clear()
            self.logger.info("Full cache invalidation completed")


def get_s3_service() -> S3Service:
    return S3Service(client=s3_client)
