"""Регресс-тесты: S3 multipart-upload abort при botocore-ошибках.

До фикса (wave 34, infra-аудит) ``upload_stream`` ловил только
``(OSError, RuntimeError, KeyError, ValueError)``. Транспортный отказ
(``BotoCoreError``) и ответ S3 с ошибкой (``ClientError``) — это
**sibling-классы**, не подклассы перечисленных, поэтому:

* multipart-upload **не abort'ился** → orphaned parts в бакете (занимают
  место, оплачиваются, видны в ``list_multipart_uploads``);
* наружу утекал сырой botocore-exception вместо ``ServiceError``,
  нарушая контракт «все ошибки → ServiceError».

Покрывает:

* ``ClientError`` на ``upload_part`` → abort + ``ServiceError``;
* ``BotoCoreError`` (connection refused) → abort + ``ServiceError``;
* успешный путь — abort не вызывается.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from botocore.exceptions import BotoCoreError, ClientError

from src.backend.core.errors import ServiceError
from src.backend.infrastructure.storage.s3 import S3ObjectStorage


class _FakeS3:
    """Минимальный stand-in для ``aiobotocore`` S3-клиента."""

    def __init__(self, fail_on: str | None = None) -> None:
        self.fail_on = fail_on
        self.aborted: list[str] = []
        self.completed = False

    async def head_bucket(self, **kwargs: Any) -> dict[str, Any]:
        return {}

    async def create_multipart_upload(self, **kwargs: Any) -> dict[str, Any]:
        return {"UploadId": "upload-1"}

    async def upload_part(self, **kwargs: Any) -> dict[str, Any]:
        if self.fail_on == "upload_part":
            raise ClientError(
                {"Error": {"Code": "InternalError", "Message": "boom"}}, "UploadPart"
            )
        return {"ETag": "etag-1"}

    async def complete_multipart_upload(self, **kwargs: Any) -> dict[str, Any]:
        self.completed = True
        return {}

    async def abort_multipart_upload(self, **kwargs: Any) -> dict[str, Any]:
        self.aborted.append(kwargs.get("UploadId", ""))
        return {}


class _FakeStorage(S3ObjectStorage):
    """S3ObjectStorage с подменённым клиентом (без сети)."""

    def __init__(self, client: _FakeS3) -> None:  # noqa: D107
        self._settings = None  # type: ignore[assignment]
        self._bucket = "bucket"
        self._prefix = ""
        self._session = None  # type: ignore[assignment]
        self._bucket_ready = True
        self.logger = None  # type: ignore[assignment]
        self._client = client
        self._client_cm = None
        self._client_lock = asyncio.Lock()

    async def _get_client(self) -> Any:
        return self._client


@pytest.fixture
def storage_factory() -> Any:
    """Фабрика fake-хранилищ."""

    def _make(fail_on: str | None = None) -> tuple[S3ObjectStorage, _FakeS3]:
        client = _FakeS3(fail_on=fail_on)
        return _FakeStorage(client), client

    return _make


async def _chunks() -> Any:
    yield b"x" * 10


@pytest.mark.asyncio
async def test_client_error_triggers_abort(storage_factory: Any) -> None:
    """``ClientError`` на upload_part → multipart abort'ится, ошибка → ServiceError."""
    storage, client = storage_factory(fail_on="upload_part")

    with pytest.raises(ServiceError):
        await storage.upload_stream("key.bin", _chunks())

    assert client.aborted == ["upload-1"]
    assert not client.completed


@pytest.mark.asyncio
async def test_boto_core_error_triggers_abort(storage_factory: Any) -> None:
    """``BotoCoreError`` (transport) → multipart abort'ится, ошибка → ServiceError."""

    class _BoomS3(_FakeS3):
        async def upload_part(self, **kwargs: Any) -> dict[str, Any]:
            raise BotoCoreError()

    client = _BoomS3()
    storage = _FakeStorage(client)

    with pytest.raises(ServiceError):
        await storage.upload_stream("key.bin", _chunks())

    assert client.aborted == ["upload-1"]


@pytest.mark.asyncio
async def test_success_path_does_not_abort(storage_factory: Any) -> None:
    """Успешный путь: abort не вызывается, multipart завершается."""
    storage, client = storage_factory()

    await storage.upload_stream("key.bin", _chunks())

    assert client.aborted == []
    assert client.completed
