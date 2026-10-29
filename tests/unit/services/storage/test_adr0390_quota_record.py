"""ADR-0390 (волна 18, кластер G1) — учёт пер-тенантных квот.

Дефект (7) [medium]: ``record_upload``/``record_delete`` не вызывались нигде
в ``src/`` — счётчики usage всегда были нулевыми, поэтому
``check_can_upload`` разрешал запись даже при ``enforce_quota=True``, а
лимиты тенанта не срабатывали никогда.

Теперь фасад фиксирует usage после успешной записи/удаления.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.core.errors import ServiceError
from src.backend.services.storage.facade import StorageFacade

pytestmark = pytest.mark.asyncio


class _QuotaResult:
    def __init__(self, allowed: bool, reason: str = "") -> None:
        self.allowed = allowed
        self.reason = reason
        self.current_files = 10
        self.current_bytes = 1024


def _storage() -> MagicMock:
    s = MagicMock()
    s.upload = AsyncMock(return_value="s3://bucket/k")
    s.upload_stream = AsyncMock(return_value="s3://bucket/k")
    s.download = AsyncMock(return_value=b"x")
    s.exists = AsyncMock(return_value=True)
    s.delete = AsyncMock(return_value=None)
    s.list_keys = AsyncMock(return_value=[])
    s.presigned_url = AsyncMock(return_value="https://signed")
    s.supports_presigned = MagicMock(return_value=True)
    return s


def _quota(allowed: bool = True, reason: str = "") -> MagicMock:
    q = MagicMock()
    q.check_can_upload = AsyncMock(return_value=_QuotaResult(allowed, reason))
    q.record_upload = AsyncMock(return_value=True)
    q.record_delete = AsyncMock(return_value=True)
    return q


@pytest.fixture
def _tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    """Подставляет tenant в ContextVar (как это делает middleware)."""
    from src.backend.core import tenancy

    monkeypatch.setattr(
        tenancy, "current_tenant", lambda: SimpleNamespace(tenant_id="bank_a")
    )


async def test_upload_records_usage(_tenant: None) -> None:
    """(7) После успешной записи usage фиксируется в квоте."""
    quota = _quota()
    facade = StorageFacade(_storage(), quota_manager=quota, plugin="ext")

    await facade.upload("k", b"payload")

    quota.record_upload.assert_awaited_once_with("bank_a", 7)


async def test_delete_records_usage(_tenant: None) -> None:
    """(7) После удаления usage уменьшается (счётчик файлов + байты)."""
    storage = _storage()
    storage.size = AsyncMock(return_value=42)
    quota = _quota()
    facade = StorageFacade(storage, quota_manager=quota, plugin="ext")

    await facade.delete("k")

    quota.record_delete.assert_awaited_once_with("bank_a", 42)


async def test_failed_upload_does_not_record_usage(_tenant: None) -> None:
    """(7) Ошибка записи не увеличивает usage (иначе квота врёт)."""
    storage = _storage()
    storage.upload = AsyncMock(side_effect=RuntimeError("s3 down"))
    quota = _quota()
    facade = StorageFacade(storage, quota_manager=quota, plugin="ext")

    with pytest.raises(ServiceError):
        await facade.upload("k", b"payload")

    quota.record_upload.assert_not_awaited()


async def test_system_uploads_are_not_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    """(7) Системные записи (без tenant) квоту не трогают."""
    from src.backend.core import tenancy

    monkeypatch.setattr(tenancy, "current_tenant", lambda: None)
    quota = _quota()
    facade = StorageFacade(_storage(), quota_manager=quota, plugin="system")

    await facade.upload("k", b"payload")

    quota.record_upload.assert_not_awaited()


async def test_quota_check_sees_recorded_usage(_tenant: None) -> None:
    """(7) usage растёт → ``check_can_upload`` начинает ограничивать.

    Сквозной сценарий: дефект (7) состоял в том, что счётчики оставались
    нулевыми и pre-check всегда разрешал запись (даже при
    ``enforce_quota=True``).
    """
    usage = {"files": 0, "bytes": 0}
    quota = MagicMock()

    async def _check(tenant_id: str, size_bytes: int) -> _QuotaResult:
        usage["files"] += 1
        usage["bytes"] += size_bytes
        return _QuotaResult(usage["files"] <= 2, "file count > limit 2")

    async def _record_upload(tenant_id: str, size_bytes: int) -> bool:
        return True

    quota.check_can_upload = AsyncMock(side_effect=_check)
    quota.record_upload = AsyncMock(side_effect=_record_upload)
    quota.record_delete = AsyncMock(return_value=True)

    facade = StorageFacade(
        _storage(), quota_manager=quota, plugin="ext", enforce_quota=True
    )

    await facade.upload("k1", b"x")
    await facade.upload("k2", b"x")

    with pytest.raises(ServiceError, match="quota exceeded"):
        await facade.upload("k3", b"x")


async def test_facade_without_explicit_manager_still_records(
    _tenant: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Фасад без явного quota-manager тоже пишет usage (ADR-0390).

    Такой фасад создаёт DI-провайдер
    (``core.di.providers.storage.get_storage_facade_provider``) — раньше
    записи через него вообще не учитывались в квотах.
    """
    quota = _quota()
    monkeypatch.setattr(
        "src.backend.services.storage.facade._default_quota_manager", lambda: quota
    )

    facade = StorageFacade(_storage(), plugin="ext")

    await facade.upload("k", b"payload")

    quota.record_upload.assert_awaited_once_with("bank_a", 7)


async def test_quota_record_failure_does_not_break_upload(_tenant: None) -> None:
    """(7) Сбой учёта usage не роняет саму запись (fail-open)."""
    quota = _quota()
    quota.record_upload = AsyncMock(side_effect=RuntimeError("redis down"))
    storage = _storage()
    facade = StorageFacade(storage, quota_manager=quota, plugin="ext")

    assert await facade.upload("k", b"payload") == "s3://bucket/k"


async def test_upload_stream_records_usage(_tenant: None) -> None:
    """(7) upload_stream (bytes) тоже фиксирует usage."""
    quota = _quota()
    facade = StorageFacade(_storage(), quota_manager=quota, plugin="ext")

    await facade.upload_stream("k", b"12345")

    quota.record_upload.assert_awaited_once_with("bank_a", 5)


def test_enforce_quota_setting_is_a_real_model_field() -> None:
    """(7) ``settings.storage.enforce_quota`` — поле модели, а не фантом.

    Composition root читал ``getattr(settings.storage, "enforce_quota", False)``,
    но такого поля в модели не было → enforcement всегда был выключен.
    """
    from src.backend.core.config.settings import settings

    assert "enforce_quota" in type(settings.storage).model_fields
