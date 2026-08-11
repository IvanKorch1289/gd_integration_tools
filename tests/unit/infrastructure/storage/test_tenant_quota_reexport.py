"""Cycle-81 (D-AUDIT-8101): canonical re-export test для TenantFileQuotaManager.

Проверяет, что ``from src.backend.infrastructure.storage import
TenantFileQuotaManager`` работает (через ``__init__.py`` re-export).

Раньше модуль был доступен только через полный dotted-path
(``from src.backend.infrastructure.storage.tenant_file_quota import ...``),
что делало его invisible для IDE auto-complete, lint'а и кросс-пакетного
импорта (например, ``services.storage.facade`` не мог получить quota
manager без полного пути).

Это test-only проверка contract'а: re-export символов в ``__all__``
должен давать identity-equal объекты с модулем-источником.
"""

from __future__ import annotations

import pytest

from src.backend.infrastructure.storage import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_FILES,
    QuotaCheckResult,
    QuotaConfig,
    TenantFileQuotaManager,
    get_tenant_file_quota_manager,
)
from src.backend.infrastructure.storage.tenant_file_quota import (
    TenantFileQuotaManager as _CanonicalTenantFileQuotaManager,
)

pytestmark = pytest.mark.unit


class TestCanonicalReExports:
    """Tests for ``__init__.py`` re-export contract."""

    def test_tenant_file_quota_manager_identity(self) -> None:
        """Re-exported symbol must be identity-equal to source."""
        assert TenantFileQuotaManager is _CanonicalTenantFileQuotaManager

    def test_quota_config_importable(self) -> None:
        assert QuotaConfig is not None
        assert QuotaConfig().enabled is True

    def test_quota_check_result_importable(self) -> None:
        assert QuotaCheckResult is not None
        # Round-trip via to_dict().
        result = QuotaCheckResult(allowed=True, reason="test")
        assert result.to_dict()["allowed"] is True

    def test_defaults_constants(self) -> None:
        assert DEFAULT_MAX_FILES == 100_000
        assert DEFAULT_MAX_BYTES == 100 * 1024 * 1024 * 1024

    def test_di_factory_importable(self) -> None:
        """``get_tenant_file_quota_manager`` callable из canonical path."""
        assert callable(get_tenant_file_quota_manager)


class TestQuotaManagerWiring:
    """Smoke test: quota manager можно инстанцировать из canonical path."""

    async def test_manager_no_redis_fail_open(self) -> None:
        """Без Redis — fail-OPEN (allowed=True, reason='redis unavailable')."""
        manager = TenantFileQuotaManager(redis_client=None)
        result = await _check(manager, tenant_id="t-acme", size_bytes=1024)
        assert result.allowed is True
        assert result.reason == "redis unavailable"

    async def test_manager_system_upload_bypass(self) -> None:
        """Без tenant_id — bypass (system uploads)."""
        manager = TenantFileQuotaManager(redis_client=None)
        result = await _check(manager, tenant_id=None, size_bytes=0)
        assert result.allowed is True
        assert result.reason == "system upload"

    async def test_manager_unsafe_tenant_rejected(self) -> None:
        """Unsafe tenant_id pattern → denied (defense-in-depth)."""
        manager = TenantFileQuotaManager(redis_client=None)
        result = await _check(manager, tenant_id="../../etc/passwd", size_bytes=0)
        assert result.allowed is False
        assert result.reason == "invalid tenant_id"


async def _check(manager: TenantFileQuotaManager, *, tenant_id, size_bytes: int):
    """Local helper: thin async wrapper to avoid pytest-asyncio config drift."""
    return await manager.check_can_upload(tenant_id, size_bytes)
