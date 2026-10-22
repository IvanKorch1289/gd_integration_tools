"""SSE и потолок TTL для presigned-URL (cycle 271, audit MEDIUM-02).

До изменений: presigned-URL не имел верхней границы TTL (``expires_in`` можно
было задать чему угодно, вплоть до ссылок «навсегда»), а настройки
server-side encryption не существовало вовсе — шифрование зависело от
конфигурации бакета, то есть определялось окружением, а не кодом.

Тесты строят backend через ``__new__`` + подстановку полей, потому что
конструктор вызывает ``_import_aioboto3()``, а ``aioboto3`` не объявлен как
зависимость (см. CRITICAL-05) и в этом окружении отсутствует.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.backend.core.config.services.storage import FileStorageSettings
from src.backend.infrastructure.storage.s3 import S3ObjectStorage


def _settings(**overrides: object) -> FileStorageSettings:
    base: dict[str, object] = {
        "provider": "minio",
        "bucket": "b",
        "endpoint": "http://minio:9000",
        "interface_endpoint": "http://minio:9001",
        "use_ssl": False,
        "verify": False,
        "timeout": 30,
        "read_timeout": 30,
        "retries": 5,
        "max_pool_connections": 20,
        "key_prefix": "uploads",
    }
    base.update(overrides)
    return FileStorageSettings(**base)  # type: ignore[arg-type]


class _FakeS3:
    def __init__(self, captured: dict) -> None:
        self._captured = captured

    async def put_object(self, **params: object) -> None:
        self._captured["put"] = params

    async def generate_presigned_url(self, op: str, **params: object) -> str:
        self._captured["presign"] = params
        return "https://signed.example/x"


class _FakeSession:
    """Async context manager — как ``_S3Session`` в реальном коде."""

    def __init__(self, s3: _FakeS3) -> None:
        self._s3 = s3

    async def __aenter__(self) -> _FakeS3:
        return self._s3

    async def __aexit__(self, *exc: object) -> None:
        return None


def _backend(settings: FileStorageSettings, captured: dict) -> S3ObjectStorage:
    """S3ObjectStorage без __init__ (не требует aioboto3)."""
    storage = S3ObjectStorage.__new__(S3ObjectStorage)
    storage._settings = settings
    storage._bucket = settings.bucket
    storage._prefix = settings.key_prefix
    storage._bucket_ready = True
    storage.logger = MagicMock()
    storage._open = lambda: _FakeSession(_FakeS3(captured))  # type: ignore[method-assign]
    storage._safe_key = (  # type: ignore[method-assign]
        lambda key: f"{storage._prefix}/{key.lstrip('/')}"
    )
    return storage


# ── settings ─────────────────────────────────────────────────────────────


def test_security_settings_exist_with_safe_defaults() -> None:
    """Шифрование включено и TTL ограничен по умолчанию."""
    s = _settings()
    assert s.server_side_encryption == "AES256"
    assert s.presign_ttl_max_seconds == 604800


# ── SSE ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upload_sends_server_side_encryption() -> None:
    captured: dict = {}
    storage = _backend(_settings(), captured)

    await storage.upload("doc.bin", b"payload", "application/octet-stream")

    put = captured["put"]
    assert put["ServerSideEncryption"] == "AES256"
    assert put["ContentType"] == "application/octet-stream"


@pytest.mark.asyncio
async def test_sse_can_be_disabled_explicitly() -> None:
    """Пустая строка — осознанное отключение, а не неявное поведение."""
    captured: dict = {}
    storage = _backend(_settings(server_side_encryption=""), captured)

    await storage.upload("doc.bin", b"payload")

    assert "ServerSideEncryption" not in captured["put"]


# ── presign TTL ceiling ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_presign_ttl_below_cap_is_untouched() -> None:
    captured: dict = {}
    storage = _backend(_settings(presign_ttl_max_seconds=604800), captured)

    await storage.presigned_url("k.bin", expires_in=900)

    assert captured["presign"]["ExpiresIn"] == 900
    storage.logger.warning.assert_not_called()


@pytest.mark.asyncio
async def test_presign_ttl_above_cap_is_clamped_and_logged() -> None:
    """``expires_in=10**9`` не должен выдавать бессрочную ссылку."""
    captured: dict = {}
    storage = _backend(_settings(presign_ttl_max_seconds=3600), captured)

    await storage.presigned_url("k.bin", expires_in=10**9)

    assert captured["presign"]["ExpiresIn"] == 3600
    storage.logger.warning.assert_called_once()
    assert "clamped" in storage.logger.warning.call_args.args[0]


@pytest.mark.asyncio
async def test_presign_cap_zero_disables_clamping() -> None:
    """Явное ``0`` снимает потолок — полезно для намеренно долгих ссылок."""
    captured: dict = {}
    storage = _backend(_settings(presign_ttl_max_seconds=0), captured)

    await storage.presigned_url("k.bin", expires_in=10**9)

    assert captured["presign"]["ExpiresIn"] == 10**9


@pytest.mark.asyncio
async def test_presign_uses_prefixed_key() -> None:
    """Скоупинг ключа сохраняется вместе с клампингом TTL."""
    captured: dict = {}
    storage = _backend(_settings(), captured)

    await storage.presigned_url("reports/2026/q1.pdf")

    assert captured["presign"]["Params"]["Key"] == "uploads/reports/2026/q1.pdf"


def test_settings_serialize_for_config_export() -> None:
    """Новые поля должны попадать в schema/dump, а не теряться."""
    dumped = _settings().model_dump()
    assert "server_side_encryption" in dumped
    assert "presign_ttl_max_seconds" in dumped
    assert isinstance(dumped["presign_ttl_max_seconds"], int)
