"""ADR-0401 — quota-manager в DI + корректный учёт байт при удалении (S3).

До фикса:

* ``core/di/providers/storage.py`` **не создавал** quota-manager — фасад,
  отданный extensions'ам, работал без ``enforce_quota`` и без явного
  ``quota_manager`` (учёт usage вёлся через ленивый default-менеджер,
  который нигде не регистрировался);
* ``infrastructure/storage/s3.py`` **не имел** ``size()`` — поэтому при
  удалении объекта счётчик байт квоты не уменьшался (уменьшался только
  счётчик файлов);
* ``TenantObjectStorage`` не проксировал ``size()`` — даже появление
  метода у S3-бэкенда не помогло бы, т.к. фасад работает через wrapper.

Тесты покрывают все три точки.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.di.providers import storage as storage_providers
from src.backend.core.interfaces.storage import ObjectStorage
from src.backend.core.tenancy import TenantContext, tenant_scope
from src.backend.infrastructure.storage.tenant_file_quota import (
    QuotaCheckResult,
    TenantFileQuotaManager,
)

pytestmark = pytest.mark.unit


class _FakeStorage(ObjectStorage):
    """Минимальный backend-заглушка."""

    def __init__(self) -> None:
        self.uploads: list[tuple[str, int]] = []
        self.deleted: list[str] = []

    async def upload(
        self, key: str, data: bytes, content_type: str | None = None
    ) -> str:
        """Запоминает загрузку."""
        self.uploads.append((key, len(data)))
        return key

    async def download(self, key: str) -> bytes:
        """Возвращает пустой payload."""
        del key
        return b""

    async def delete(self, key: str) -> None:
        """Запоминает удаление."""
        self.deleted.append(key)

    async def exists(self, key: str) -> bool:
        """Всегда ``False``."""
        del key
        return False

    async def list_keys(self, prefix: str = "") -> list[str]:
        """Пустой список."""
        del prefix
        return []

    async def presigned_url(self, key: str, expires_in: int = 3600) -> str:
        """Фиктивный URL."""
        del key, expires_in
        return "file://stub"

    async def size(self, key: str) -> int:
        """Фиксированный размер объекта (17 байт)."""
        del key
        return 17


class _FakeQuotaManager:
    """Заглушка quota-manager'а (пишет вызовы в списки)."""

    def __init__(self) -> None:
        self.uploads: list[tuple[str | None, int]] = []
        self.deletes: list[tuple[str | None, int]] = []

    async def check_can_upload(
        self, tenant_id: str | None, size_bytes: int
    ) -> QuotaCheckResult:
        """Всегда разрешает."""
        del tenant_id, size_bytes
        return QuotaCheckResult(allowed=True)

    async def record_upload(self, tenant_id: str | None, size_bytes: int) -> bool:
        """Запоминает upload."""
        self.uploads.append((tenant_id, size_bytes))
        return True

    async def record_delete(self, tenant_id: str | None, size_bytes: int) -> bool:
        """Запоминает delete."""
        self.deletes.append((tenant_id, size_bytes))
        return True


@pytest.fixture(autouse=True)
def _reset_overrides() -> Any:
    """Сбрасывает override-ы storage-провайдера после теста."""
    saved = dict(storage_providers._overrides)
    yield
    storage_providers._overrides.clear()
    storage_providers._overrides.update(saved)


# ── DI-провайдер квот ─────────────────────────────────────────────────────


def test_quota_manager_provider_returns_manager() -> None:
    """DI-провайдер обязан отдавать менеджер пер-тенантных квот."""
    manager = storage_providers.get_quota_manager_provider()

    assert isinstance(manager, TenantFileQuotaManager)


def test_quota_manager_provider_uses_override() -> None:
    """Зарегистрированный менеджер используется провайдером (test-инъекция)."""
    fake = _FakeQuotaManager()
    storage_providers.set_quota_manager_provider(fake)

    assert storage_providers.get_quota_manager_provider() is fake


@pytest.mark.asyncio
async def test_storage_facade_provider_uses_registered_quota_manager() -> None:
    """Фасад из DI обязан писать usage в зарегистрированный quota-manager."""
    fake_quota = _FakeQuotaManager()
    fake_storage = _FakeStorage()
    storage_providers.set_quota_manager_provider(fake_quota)
    storage_providers.set_object_storage_provider(fake_storage)

    facade = storage_providers.get_storage_facade_provider(plugin="extension")
    assert facade is not None

    with tenant_scope(TenantContext(tenant_id="bank_a")):
        await facade.upload("report.pdf", b"x" * 17)

    assert fake_quota.uploads == [("bank_a", 17)]


@pytest.mark.asyncio
async def test_storage_facade_delete_decrements_quota_bytes() -> None:
    """Удаление объекта уменьшает счётчик **байт** квоты (нужен ``size()``)."""
    fake_quota = _FakeQuotaManager()
    fake_storage = _FakeStorage()
    storage_providers.set_quota_manager_provider(fake_quota)
    storage_providers.set_object_storage_provider(fake_storage)

    facade = storage_providers.get_storage_facade_provider(plugin="extension")
    assert facade is not None

    with tenant_scope(TenantContext(tenant_id="bank_a")):
        await facade.delete("report.pdf")

    assert fake_quota.deletes == [("bank_a", 17)]


# ── size() у S3-бэкенда и у tenant-wrapper'а ──────────────────────────────


@pytest.mark.asyncio
async def test_tenant_object_storage_proxies_size() -> None:
    """``TenantObjectStorage`` обязан проксировать ``size()`` на backend."""
    from src.backend.infrastructure.storage.tenant_wrapper import TenantObjectStorage

    class _SizedStorage(_FakeStorage):
        async def size(self, key: str) -> int:
            """Фиксированный размер объекта."""
            del key
            return 42

    wrapper = TenantObjectStorage(_SizedStorage())

    assert await wrapper.size("report.pdf") == 42


@pytest.mark.asyncio
async def test_s3_object_storage_size_returns_content_length() -> None:
    """``S3ObjectStorage.size()`` возвращает ContentLength объекта."""
    from src.backend.core.config.services.storage import FileStorageSettings
    from src.backend.infrastructure.storage.s3 import S3ObjectStorage

    settings = FileStorageSettings(
        enabled=True,
        provider="minio",
        bucket="b",
        access_key="AKIA-TEST",
        secret_key="secret",
        endpoint="http://localhost:9000",
        interface_endpoint="http://localhost:9000",
        use_ssl=False,
        verify=False,
    )
    storage = S3ObjectStorage(settings)

    class _FakeS3:
        async def head_object(self, **kwargs: Any) -> dict[str, Any]:
            """Возвращает фиктивный ContentLength."""
            del kwargs
            return {"ContentLength": 1234}

    storage._client = _FakeS3()

    assert await storage.size("report.pdf") == 1234


@pytest.mark.asyncio
async def test_s3_object_storage_size_missing_object_is_zero() -> None:
    """Отсутствующий объект даёт ``0`` (без исключения)."""
    from botocore.exceptions import ClientError

    from src.backend.core.config.services.storage import FileStorageSettings
    from src.backend.infrastructure.storage.s3 import S3ObjectStorage

    settings = FileStorageSettings(
        enabled=True,
        provider="minio",
        bucket="b",
        access_key="AKIA-TEST",
        secret_key="secret",
        endpoint="http://localhost:9000",
        interface_endpoint="http://localhost:9000",
        use_ssl=False,
        verify=False,
    )
    storage = S3ObjectStorage(settings)

    class _MissingS3:
        async def head_object(self, **kwargs: Any) -> dict[str, Any]:
            """Эмулирует 404."""
            del kwargs
            raise ClientError(
                {"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject"
            )

    storage._client = _MissingS3()

    assert await storage.size("missing.pdf") == 0
