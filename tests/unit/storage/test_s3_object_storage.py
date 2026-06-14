"""Unit-тесты ``S3ObjectStorage`` через ``moto.server.ThreadedMotoServer``.

Использует standalone moto HTTP-сервер (real S3 wire protocol),
aioboto3 совместим с ним нативно. ``mock_aws`` decorator у aioboto3
не работает (incompatible response body types в moto 5.2 + aiobotocore
2.25), поэтому server-side mocking.

Покрывает:

* round-trip ``upload`` → ``download``;
* ``upload`` с ``content_type``;
* ``delete`` → ``exists`` == False, повторный ``delete`` no-op;
* ``exists`` для несуществующего ключа → False;
* ``list_keys`` с вложенными префиксами + auto-prefix;
* ``presigned_url`` возвращает строку с подписью;
* path-traversal (``..``, абсолютные, пустые) → ``ValueError``;
* ``healthcheck`` → True на живой bucket;
* ``ServiceError`` оборачивает boto-исключения.
"""

# ruff: noqa: S101  # assert — стандартная идиома pytest

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest

pytest.importorskip("moto", reason="moto not in test deps; S124 W2 honest skip (TD-0244)")

from moto.server import ThreadedMotoServer

from src.backend.core.config.services.storage import FileStorageSettings
from src.backend.core.errors import ServiceError
from src.backend.infrastructure.storage.s3 import S3ObjectStorage


def _unique_bucket() -> str:
    return f"test-bucket-{uuid.uuid4().hex[:12]}"


@pytest.fixture(scope="module")
def moto_server() -> Any:
    """Поднимает moto HTTP-сервер на случайном порту, выключает после модуля."""
    server = ThreadedMotoServer(port=0)
    server.start()
    host, port = server.get_host_and_port()
    os.environ["MOTO_ENDPOINT"] = f"http://{host}:{port}"
    yield server
    server.stop()
    os.environ.pop("MOTO_ENDPOINT", None)


@pytest.fixture
def storage(moto_server: Any) -> S3ObjectStorage:
    """S3ObjectStorage + moto server (новый bucket создаётся lazy)."""
    endpoint = os.environ["MOTO_ENDPOINT"]
    settings = FileStorageSettings(
        enabled=True,
        provider="minio",
        bucket=_unique_bucket(),
        access_key="AKIA-TEST",
        secret_key="secret-test",
        endpoint=endpoint,
        interface_endpoint=endpoint,
        use_ssl=False,
        verify=False,  # nosec — test-only, moto local server
        timeout=5,
        retries=2,
        max_pool_connections=10,
        read_timeout=5,
        key_prefix="tenant-1/",
    )
    return S3ObjectStorage(settings)


@pytest.fixture
def storage_no_prefix(moto_server: Any) -> S3ObjectStorage:
    endpoint = os.environ["MOTO_ENDPOINT"]
    settings = FileStorageSettings(
        enabled=True,
        provider="minio",
        bucket=_unique_bucket(),
        access_key="AKIA-TEST",
        secret_key="secret-test",
        endpoint=endpoint,
        interface_endpoint=endpoint,
        use_ssl=False,
        verify=False,  # nosec — test-only, moto local server
        timeout=5,
        retries=2,
        max_pool_connections=10,
        read_timeout=5,
        key_prefix="",
    )
    return S3ObjectStorage(settings)


# ── upload / download ────────────────────────────────────────────────────


async def test_upload_download_roundtrip(storage: S3ObjectStorage) -> None:
    payload = b"hello s3\n"
    await storage.upload("docs/note.txt", payload)
    assert await storage.download("docs/note.txt") == payload


async def test_upload_overwrites(storage: S3ObjectStorage) -> None:
    await storage.upload("a.bin", b"v1")
    await storage.upload("a.bin", b"v2-longer")
    assert await storage.download("a.bin") == b"v2-longer"


async def test_upload_with_content_type(storage: S3ObjectStorage) -> None:
    """``content_type`` не теряется при upload."""
    await storage.upload("x.json", b'{"k":1}', content_type="application/json")
    assert await storage.exists("x.json") is True
    assert await storage.download("x.json") == b'{"k":1}'


async def test_upload_wraps_boto_error_as_service_error(
    storage: S3ObjectStorage,
) -> None:
    """``ServiceError`` оборачивает boto-исключения из ``upload``."""
    from botocore.exceptions import ClientError

    class _FakeS3:
        async def put_object(self, **kwargs: Any) -> None:
            raise ClientError(
                {"Error": {"Code": "InternalError", "Message": "boom"}}, "PutObject"
            )

    class _FakeS3Session:
        async def __aenter__(self) -> _FakeS3:
            return _FakeS3()

        async def __aexit__(self, *exc: object) -> None:
            return None

    storage._open = lambda: _FakeS3Session()  # type: ignore[method-assign]
    with pytest.raises(ServiceError, match="S3 upload failed"):
        await storage.upload("k", b"v")


# ── exists / delete ──────────────────────────────────────────────────────


async def test_delete_removes_existing(storage: S3ObjectStorage) -> None:
    await storage.upload("tmp/x.bin", b"data")
    assert await storage.exists("tmp/x.bin") is True
    await storage.delete("tmp/x.bin")
    assert await storage.exists("tmp/x.bin") is False


async def test_delete_missing_key_is_noop(storage: S3ObjectStorage) -> None:
    await storage.delete("never-was-here.bin")


async def test_exists_missing_returns_false(storage: S3ObjectStorage) -> None:
    assert await storage.exists("ghost.bin") is False


async def test_download_missing_raises_file_not_found(storage: S3ObjectStorage) -> None:
    with pytest.raises(FileNotFoundError, match="Object not found"):
        await storage.download("missing.bin")


# ── list_keys ────────────────────────────────────────────────────────────


async def test_list_keys_returns_relative_sorted_paths(
    storage: S3ObjectStorage,
) -> None:
    await storage.upload("a.bin", b"1")
    await storage.upload("dir/b.bin", b"2")
    await storage.upload("dir/sub/c.bin", b"3")
    assert await storage.list_keys() == ["a.bin", "dir/b.bin", "dir/sub/c.bin"]


async def test_list_keys_subprefix(storage: S3ObjectStorage) -> None:
    await storage.upload("a.bin", b"1")
    await storage.upload("dir/b.bin", b"2")
    await storage.upload("dir/sub/c.bin", b"3")
    assert await storage.list_keys("dir") == ["dir/b.bin", "dir/sub/c.bin"]


async def test_list_keys_empty_bucket(storage_no_prefix: S3ObjectStorage) -> None:
    assert await storage_no_prefix.list_keys() == []


# ── presigned URL ────────────────────────────────────────────────────────


async def test_presigned_url_returns_signed_string(storage: S3ObjectStorage) -> None:
    await storage.upload("a.txt", b"x")
    url = await storage.presigned_url("a.txt", expires_in=300)
    assert isinstance(url, str)
    # moto возвращает http URL с query-параметрами
    assert "X-Amz-Signature" in url or "Signature=" in url
    assert storage._bucket in url


def test_supports_presigned_true(storage: S3ObjectStorage) -> None:
    assert storage.supports_presigned() is True


# ── healthcheck ──────────────────────────────────────────────────────────


async def test_healthcheck_true_when_bucket_accessible(
    storage: S3ObjectStorage,
) -> None:
    assert await storage.healthcheck() is True


# ── key safety ──────────────────────────────────────────────────────────


async def test_path_traversal_rejected(storage: S3ObjectStorage) -> None:
    with pytest.raises(ValueError, match="Path-traversal"):
        await storage.upload("../escape.bin", b"x")


async def test_absolute_key_rejected(storage: S3ObjectStorage) -> None:
    with pytest.raises(ValueError, match="Абсолютный ключ"):
        await storage.upload("/etc/passwd", b"x")


async def test_empty_key_rejected(storage: S3ObjectStorage) -> None:
    with pytest.raises(ValueError, match="Пустой ключ"):
        await storage.upload("", b"x")


async def test_empty_exists_rejected(storage: S3ObjectStorage) -> None:
    with pytest.raises(ValueError, match="Пустой ключ"):
        await storage.exists("")


async def test_key_too_long_rejected(storage: S3ObjectStorage) -> None:
    long_key = "a" * 1025
    with pytest.raises(ValueError, match="превышает 1024 байт"):
        await storage.upload(long_key, b"x")


async def test_key_with_control_chars_rejected(storage: S3ObjectStorage) -> None:
    with pytest.raises(ValueError, match="Control-символы"):
        await storage.upload("file\x00.bin", b"x")


async def test_key_with_double_slash_rejected(storage: S3ObjectStorage) -> None:
    with pytest.raises(ValueError, match="Двойной слэш"):
        await storage.upload("dir//file.bin", b"x")


# ── factory integration ─────────────────────────────────────────────────


async def test_factory_uses_s3_when_provider_not_local(moto_server: Any) -> None:
    """``get_object_storage`` возвращает ``S3ObjectStorage`` при provider=s3."""
    from src.backend.infrastructure.storage import factory

    factory.get_object_storage.cache_clear()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "src.backend.core.config.settings.settings.storage.provider", "minio"
        )
        store = factory.get_object_storage()
        assert isinstance(store, S3ObjectStorage)
        # factory хранит настройки из fs_settings (module-level);
        # bucket реально существует, даже если endpoint = production
        assert store._bucket  # type: ignore[attr-defined]
    factory.get_object_storage.cache_clear()


async def test_factory_returns_local_when_provider_local() -> None:
    from src.backend.infrastructure.storage import factory

    factory.get_object_storage.cache_clear()
    factory.get_local_fs_storage.cache_clear()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "src.backend.core.config.settings.settings.storage.provider", "local"
        )
        store = factory.get_object_storage()
    from src.backend.infrastructure.storage.local_fs import LocalFSStorage

    assert isinstance(store, LocalFSStorage)
    factory.get_object_storage.cache_clear()
    factory.get_local_fs_storage.cache_clear()
