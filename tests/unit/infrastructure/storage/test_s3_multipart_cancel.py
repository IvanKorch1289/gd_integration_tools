"""S183 W2 #1 — D-AUDIT-#14: S3 multipart abort on cancel/OOM.

Per multi-agent audit (carry-over D-AUDIT-#14) + confirm by current
``s3.py:332`` source: ``except (OSError, RuntimeError, KeyError, ValueError)``
does NOT catch ``asyncio.CancelledError`` or ``MemoryError``. On cancel/OOM
mid-upload, multipart upload остаётся orphan в S3.

Pre-fix: тесты должны fall (или expired-cleanup-via-aiobotocore НЕ
срабатывает — empirically verified в audit).
Post-fix: ``abort_multipart_upload`` called + caller sees original
CancelledError/MemoryError re-raised.

Strict-test policy per D-LESSON-11: NO lax `with x: pass``.
"""

from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ponytail: deps (botocore, aiobotocore) — optional. Mocked via sys.modules
# to avoid collection-error in venv without boto3 (per D-LESSON-7 pattern).
_boto_stub = MagicMock()
_boto_stub.config = MagicMock()
_boto_stub.exceptions = MagicMock()
_boto_stub.exceptions.BotoCoreError = type("BotoCoreError", (Exception,), {})
_boto_stub.exceptions.ClientError = type("ClientError", (Exception,), {})
sys.modules.setdefault("botocore", _boto_stub)
sys.modules.setdefault("botocore.config", _boto_stub.config)
sys.modules.setdefault("botocore.exceptions", _boto_stub.exceptions)

from src.backend.core.errors import ServiceError
from src.backend.infrastructure.storage.s3 import S3ObjectStorage


def _make_storage() -> S3ObjectStorage:
    """Build S3ObjectStorage without touching real S3."""
    storage = S3ObjectStorage.__new__(S3ObjectStorage)
    storage._bucket = "test-bucket"
    storage._prefix = None
    storage._client = MagicMock()
    storage.logger = MagicMock()
    return storage


def _make_stream(chunks: list[bytes]):
    """Return async generator that yields chunks (NOT a context manager).

    Source checks ``isinstance(stream, AsyncIterable)`` — AsyncGenerator
    satisfies this.
    """

    async def _gen():
        for c in chunks:
            yield c

    return _gen()


def _patched_open(s3_mock: AsyncMock):
    """Mock ``S3ObjectStorage._open`` to yield a single aioboto3 client mock."""

    @asynccontextmanager
    async def _open():
        yield s3_mock

    return _open


@pytest.mark.asyncio
async def test_cancelled_error_triggers_abort(monkeypatch) -> None:
    """``asyncio.CancelledError`` mid-upload → ``abort_multipart_upload`` called."""
    storage = _make_storage()
    s3_mock = AsyncMock()
    s3_mock.create_multipart_upload = AsyncMock(
        return_value={"UploadId": "upload-cancel-test"}
    )

    async def upload_part_raise_cancel(**kwargs) -> dict:
        raise asyncio.CancelledError("task cancelled mid-upload")

    s3_mock.upload_part = upload_part_raise_cancel
    s3_mock.abort_multipart_upload = AsyncMock(return_value={})

    monkeypatch.setattr(storage, "_open", _patched_open(s3_mock))
    monkeypatch.setattr(storage, "_safe_key", lambda k: k)

    big_chunk = b"x" * (8 * 1024 * 1024 + 1)  # > part_size, triggers upload_part
    stream = _make_stream([big_chunk])

    with pytest.raises(asyncio.CancelledError):
        await storage.upload_stream(key="k-cancel", stream=stream)

    s3_mock.abort_multipart_upload.assert_called_once_with(
        Bucket="test-bucket", Key="k-cancel", UploadId="upload-cancel-test"
    )


@pytest.mark.asyncio
async def test_memory_error_triggers_abort(monkeypatch) -> None:
    """``MemoryError`` mid-upload → ``abort_multipart_upload`` called."""
    storage = _make_storage()
    s3_mock = AsyncMock()
    s3_mock.create_multipart_upload = AsyncMock(
        return_value={"UploadId": "upload-mem-test"}
    )

    async def upload_part_raise_mem(**kwargs) -> dict:
        raise MemoryError("OOM")

    s3_mock.upload_part = upload_part_raise_mem
    s3_mock.abort_multipart_upload = AsyncMock(return_value={})

    monkeypatch.setattr(storage, "_open", _patched_open(s3_mock))
    monkeypatch.setattr(storage, "_safe_key", lambda k: k)

    big_chunk = b"x" * (8 * 1024 * 1024 + 1)
    stream = _make_stream([big_chunk])

    with pytest.raises(MemoryError):
        await storage.upload_stream(key="k-mem", stream=stream)

    s3_mock.abort_multipart_upload.assert_called_once_with(
        Bucket="test-bucket", Key="k-mem", UploadId="upload-mem-test"
    )


@pytest.mark.asyncio
async def test_os_error_still_wrapped_as_service_error(monkeypatch) -> None:
    """Backward-compat: OSError wrapped as ServiceError (existing path)."""
    storage = _make_storage()
    s3_mock = AsyncMock()
    s3_mock.create_multipart_upload = AsyncMock(
        return_value={"UploadId": "upload-os-test"}
    )
    s3_mock.upload_part = AsyncMock(side_effect=OSError("connection reset"))
    s3_mock.abort_multipart_upload = AsyncMock(return_value={})

    monkeypatch.setattr(storage, "_open", _patched_open(s3_mock))
    monkeypatch.setattr(storage, "_safe_key", lambda k: k)

    big_chunk = b"x" * (8 * 1024 * 1024 + 1)
    stream = _make_stream([big_chunk])

    with pytest.raises(ServiceError, match="S3 upload_stream failed"):
        await storage.upload_stream(key="k-os", stream=stream)

    s3_mock.abort_multipart_upload.assert_called_once_with(
        Bucket="test-bucket", Key="k-os", UploadId="upload-os-test"
    )


@pytest.mark.asyncio
async def test_abort_failure_logged_but_original_exception_propagates(
    monkeypatch,
) -> None:
    """If abort itself fails on cancel, original CancelledError still propagates."""
    storage = _make_storage()
    s3_mock = AsyncMock()
    s3_mock.create_multipart_upload = AsyncMock(
        return_value={"UploadId": "upload-double-fail"}
    )

    async def upload_part_raise_cancel(**kwargs) -> dict:
        raise asyncio.CancelledError("task cancelled")

    s3_mock.upload_part = upload_part_raise_cancel
    # abort ITSELF raises — should be logged, not propagated
    s3_mock.abort_multipart_upload = AsyncMock(
        side_effect=OSError("abort S3 also down")
    )

    monkeypatch.setattr(storage, "_open", _patched_open(s3_mock))
    monkeypatch.setattr(storage, "_safe_key", lambda k: k)

    big_chunk = b"x" * (8 * 1024 * 1024 + 1)
    stream = _make_stream([big_chunk])

    with pytest.raises(asyncio.CancelledError):
        await storage.upload_stream(key="k-double-fail", stream=stream)

    s3_mock.abort_multipart_upload.assert_called_once()
    storage.logger.exception.assert_called()


@pytest.mark.asyncio
async def test_successful_upload_does_not_abort(monkeypatch) -> None:
    """Happy path: NO abort call, returns full_key."""
    storage = _make_storage()
    s3_mock = AsyncMock()
    s3_mock.create_multipart_upload = AsyncMock(return_value={"UploadId": "ok-upload"})
    s3_mock.upload_part = AsyncMock(return_value={"ETag": "etag-abc"})
    s3_mock.complete_multipart_upload = AsyncMock(return_value={})
    s3_mock.abort_multipart_upload = AsyncMock(return_value={})

    monkeypatch.setattr(storage, "_open", _patched_open(s3_mock))
    monkeypatch.setattr(storage, "_safe_key", lambda k: k)

    big_chunk = b"x" * (8 * 1024 * 1024 + 1)
    stream = _make_stream([big_chunk])

    result = await storage.upload_stream(key="k-success", stream=stream)

    assert result == "k-success"
    s3_mock.abort_multipart_upload.assert_not_called()
    s3_mock.complete_multipart_upload.assert_called_once()
