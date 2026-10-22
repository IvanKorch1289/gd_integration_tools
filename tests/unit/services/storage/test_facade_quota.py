"""Quota gate в ``StorageFacade`` (cycle 271 audit, CRITICAL-02).

``tenant_file_quota`` был полностью реализован, но не имел **ни одного**
вызывающего вне собственного модуля (``check_can_upload`` / ``record_upload``
не встречались нигде в src/ и extensions/). То есть ни один upload никогда не
проверялся, а пер-тенантные квоты были мёртвым кодом.

По решению (grilling, раунд 2) enforcement стартует в alert-only режиме:
превышение логируется и считается, но не блокирует запись — так видно реальное
распределение до включения жёсткого режима.
"""

from __future__ import annotations

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


def _quota(allowed: bool, reason: str = "bytes 999 > limit 100") -> MagicMock:
    q = MagicMock()
    q.check_can_upload = AsyncMock(return_value=_QuotaResult(allowed, reason))
    return q


@pytest.fixture
def _tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    """Подставляет tenant в ContextVar, как это делает middleware."""
    from types import SimpleNamespace

    from src.backend.core import tenancy

    monkeypatch.setattr(
        tenancy, "current_tenant", lambda: SimpleNamespace(tenant_id="bank_a")
    )


async def test_quota_is_actually_consulted(_tenant: None) -> None:
    """Регрессия на «мёртвый код»: менеджер обязан вызываться."""
    quota = _quota(allowed=True)
    facade = StorageFacade(_storage(), quota_manager=quota, plugin="ext")

    await facade.upload("k", b"payload")

    quota.check_can_upload.assert_awaited_once_with("bank_a", 7)


async def test_alert_only_allows_write_but_logs_error(
    _tenant: None, caplog: pytest.LogCaptureFixture
) -> None:
    """Alert-only: запись проходит, но превышение видно в логах и метриках."""
    storage = _storage()
    facade = StorageFacade(storage, quota_manager=_quota(False), plugin="ext")

    with caplog.at_level("ERROR"):
        result = await facade.upload("k", b"payload")

    assert result == "s3://bucket/k", "alert-only не должен блокировать запись"
    storage.upload.assert_awaited_once()
    assert "QUOTA EXCEEDED" in caplog.text


async def test_enforce_mode_blocks_write(_tenant: None) -> None:
    """Включённый enforcement превращает превышение в ServiceError."""
    storage = _storage()
    facade = StorageFacade(
        storage, quota_manager=_quota(False), plugin="ext", enforce_quota=True
    )

    with pytest.raises(ServiceError, match="quota exceeded"):
        await facade.upload("k", b"payload")

    storage.upload.assert_not_awaited()


async def test_system_uploads_bypass_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без tenant квота не применяется (system uploads)."""
    from src.backend.core import tenancy

    monkeypatch.setattr(tenancy, "current_tenant", lambda: None)
    quota = _quota(False)
    facade = StorageFacade(_storage(), quota_manager=quota, plugin="system")

    await facade.upload("k", b"payload")

    quota.check_can_upload.assert_not_awaited()


async def test_no_quota_manager_means_no_check() -> None:
    """Фасад без quota-manager работает как раньше (обратная совместимость)."""
    facade = StorageFacade(_storage(), plugin="ext")
    assert await facade.upload("k", b"payload") == "s3://bucket/k"


async def test_quota_failure_does_not_break_upload(_tenant: None) -> None:
    """Сбой самой проверки не должен ронять запись (fail-open с логом)."""
    quota = MagicMock()
    quota.check_can_upload = AsyncMock(side_effect=RuntimeError("redis down"))
    storage = _storage()
    facade = StorageFacade(storage, quota_manager=quota, plugin="ext")

    assert await facade.upload("k", b"payload") == "s3://bucket/k"
    storage.upload.assert_awaited_once()


async def test_upload_stream_checks_quota_for_bytes(_tenant: None) -> None:
    """Для bytes через upload_stream квота тоже применяется."""
    quota = _quota(allowed=True)
    facade = StorageFacade(_storage(), quota_manager=quota, plugin="ext")

    await facade.upload_stream("k", b"12345")

    quota.check_can_upload.assert_awaited_once_with("bank_a", 5)


async def test_facade_view_inherits_quota_settings() -> None:
    """Plugin-view не должен обходить alert-only/enforcement настройки."""
    from src.backend.services.storage import get_storage_facade

    quota = _quota(allowed=True)
    root = StorageFacade(
        _storage(), plugin="system", quota_manager=quota, enforce_quota=True
    )

    # Регистрируем корневой фасад, чтобы get_storage_facade его нашёл.
    from src.backend.core.svcs_registry import has_service, register_factory

    if not has_service(StorageFacade):
        register_factory(StorageFacade, lambda: root)

    view = get_storage_facade(plugin="ext-1")
    assert view._quota is quota
    assert view._enforce_quota is True
