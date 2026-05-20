"""Unit-тесты ``S3Client.put_object_multipart`` (S13 K2 W1).

Использует mock aiobotocore-client'а — реальное взаимодействие с S3
покрывается отдельным integration-тестом (под testcontainer MinIO).
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


class _FakeS3Client:
    """Имитирует aiobotocore S3 client для multipart upload."""

    def __init__(self) -> None:
        self.parts_received: list[bytes] = []
        self.completed = False
        self.aborted = False
        self.upload_id = "test-upload-id"

    async def create_multipart_upload(self, **kwargs: Any) -> dict[str, Any]:
        return {"UploadId": self.upload_id}

    async def upload_part(
        self, *, Bucket: str, Key: str, UploadId: str, PartNumber: int, Body: bytes
    ) -> dict[str, Any]:
        assert UploadId == self.upload_id
        self.parts_received.append(Body)
        return {"ETag": f'"etag-part-{PartNumber}"'}

    async def complete_multipart_upload(self, **kwargs: Any) -> dict[str, Any]:
        self.completed = True
        return {"ETag": '"final-etag"'}

    async def abort_multipart_upload(self, **kwargs: Any) -> dict[str, Any]:
        self.aborted = True
        return {}


async def _make_stream(chunks: list[bytes]):
    for chunk in chunks:
        yield chunk


@pytest.fixture
def s3_client_with_fake(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, _FakeS3Client]:
    """Возвращает S3Client с подменённым client_context на FakeS3Client."""
    from contextlib import asynccontextmanager

    from src.backend.core.config.services.storage import FileStorageSettings
    from src.backend.infrastructure.clients.storage.s3_pool import S3Client

    from pathlib import Path

    settings = FileStorageSettings(
        enabled=False,  # отключает aiobotocore init
        provider="local",
        local_storage_path=Path("/tmp/test"),
        bucket="test-bucket",
        access_key="x",
        secret_key="x",
        endpoint="http://minio:9000",
        interface_endpoint="http://minio:9000",
        use_ssl=False,
        verify=False,
        timeout=30,
        retries=3,
        max_pool_connections=10,
        read_timeout=30,
        key_prefix="",
    )
    client = S3Client(settings)
    fake = _FakeS3Client()

    @asynccontextmanager
    async def _ctx() -> Any:
        yield fake

    # ensure_connected decorator проверяет is_connected (нужны _client и _exit_stack).
    client._client = MagicMock()
    client._exit_stack = MagicMock()  # type: ignore[assignment]
    monkeypatch.setattr(client, "client_context", _ctx)
    return client, fake


@pytest.mark.asyncio
async def test_multipart_upload_single_part_buffer(s3_client_with_fake) -> None:
    client, fake = s3_client_with_fake
    chunks = [b"x" * (3 * 1024 * 1024)]  # 3MB < 5MB min, должен пойти как 1 part
    etag = await client.put_object_multipart(
        key="test.bin", stream=_make_stream(chunks), part_size=5 * 1024 * 1024
    )
    assert etag == '"final-etag"'
    assert fake.completed is True
    assert fake.aborted is False
    assert len(fake.parts_received) == 1
    assert fake.parts_received[0] == chunks[0]


@pytest.mark.asyncio
async def test_multipart_upload_splits_to_5mb_parts(s3_client_with_fake) -> None:
    client, fake = s3_client_with_fake
    # 13MB поток → 2 части по 5MB + 1 часть 3MB = 3 parts
    chunks = [b"a" * (4 * 1024 * 1024), b"b" * (4 * 1024 * 1024), b"c" * (5 * 1024 * 1024)]
    etag = await client.put_object_multipart(
        key="test.bin", stream=_make_stream(chunks), part_size=5 * 1024 * 1024
    )
    assert etag == '"final-etag"'
    assert fake.completed is True
    assert sum(len(p) for p in fake.parts_received) == 13 * 1024 * 1024
    # Хотя бы 2 parts (минимум один полный 5MB и финальный остаток).
    assert len(fake.parts_received) >= 2


@pytest.mark.asyncio
async def test_multipart_upload_empty_stream_aborts(s3_client_with_fake) -> None:
    client, fake = s3_client_with_fake
    etag = await client.put_object_multipart(
        key="test.bin", stream=_make_stream([]), part_size=5 * 1024 * 1024
    )
    assert etag == ""
    assert fake.aborted is True
    assert fake.completed is False


@pytest.mark.asyncio
async def test_multipart_upload_min_part_size_5mb(s3_client_with_fake) -> None:
    """Если передан part_size < 5MB — округляется до 5MB."""
    client, fake = s3_client_with_fake
    # 6MB поток с part_size=1MB → должен пойти как 1 part 6MB (5MB min достигнут)
    chunks = [b"x" * (6 * 1024 * 1024)]
    await client.put_object_multipart(
        key="test.bin", stream=_make_stream(chunks), part_size=1024
    )
    # Проверяем что хотя бы один part был отправлен с размером >= 5MB.
    assert len(fake.parts_received) >= 1
    assert max(len(p) for p in fake.parts_received) >= 5 * 1024 * 1024


@pytest.mark.asyncio
async def test_multipart_upload_aborts_on_exception(s3_client_with_fake) -> None:
    client, fake = s3_client_with_fake
    # Перебиваем upload_part так, чтобы он падал.
    fake.upload_part = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]
    chunks = [b"x" * (6 * 1024 * 1024)]
    with pytest.raises(RuntimeError):
        await client.put_object_multipart(
            key="test.bin", stream=_make_stream(chunks), part_size=5 * 1024 * 1024
        )
    assert fake.aborted is True
