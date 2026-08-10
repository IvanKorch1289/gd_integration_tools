"""Cycle-15 (D-AUDIT-1507): tests for TenantFileQuotaManager."""

from __future__ import annotations

import pytest

from src.backend.infrastructure.storage.tenant_file_quota import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_FILES,
    QuotaCheckResult,
    QuotaConfig,
    TenantFileQuotaManager,
)

pytestmark = pytest.mark.unit


class TestQuotaConfig:
    """Tests for :class:`QuotaConfig` defaults and parsing."""

    def test_defaults(self) -> None:
        config = QuotaConfig()
        assert config.max_files == DEFAULT_MAX_FILES
        assert config.max_bytes == DEFAULT_MAX_BYTES
        assert config.enabled is True

    def test_from_dict_none(self) -> None:
        assert QuotaConfig.from_dict(None) == QuotaConfig()

    def test_from_dict_custom(self) -> None:
        config = QuotaConfig.from_dict(
            {"max_files": 5000, "max_bytes": 1024, "enabled": False}
        )
        assert config.max_files == 5000
        assert config.max_bytes == 1024
        assert config.enabled is False


class TestSafeTenantId:
    """Tests for tenant_id validation."""

    def test_safe_ids(self) -> None:
        for tid in ["test", "acme_corp", "tenant-1", "ABC_xyz_123"]:
            assert TenantFileQuotaManager._is_safe_tenant_id(tid) is True

    def test_unsafe_ids(self) -> None:
        for tid in [
            "",  # empty
            "a" * 65,  # too long
            "tenant with spaces",
            "../etc/passwd",
            "tenant;DROP TABLE",
            "tënant_ünïcödé",  # non-ASCII
        ]:
            assert TenantFileQuotaManager._is_safe_tenant_id(tid) is False


class TestQuotaCheckNoRedis:
    """Tests for :meth:`check_can_upload` without Redis (fail-OPEN)."""

    async def test_system_upload_bypass(self) -> None:
        mgr = TenantFileQuotaManager(redis_client=None)
        result = await mgr.check_can_upload(tenant_id=None, size_bytes=1024)
        assert result.allowed is True
        assert result.reason == "system upload"

    async def test_no_redis_bypass(self) -> None:
        """Без Redis — fail-OPEN с reason ``redis unavailable``."""
        mgr = TenantFileQuotaManager(redis_client=None)
        result = await mgr.check_can_upload(tenant_id="acme", size_bytes=1024)
        assert result.allowed is True
        assert result.reason == "redis unavailable"

    async def test_quota_disabled_bypass(self) -> None:
        """Quota disabled → bypass."""
        mgr = TenantFileQuotaManager(
            redis_client=None,
            config=QuotaConfig(enabled=False),
        )
        result = await mgr.check_can_upload(tenant_id="acme", size_bytes=1024)
        assert result.allowed is True
        assert result.reason == "quota disabled"

    async def test_unsafe_tenant_id_rejected(self) -> None:
        """Unsafe tenant_id → rejected (no Redis needed)."""
        mgr = TenantFileQuotaManager(redis_client=None)
        result = await mgr.check_can_upload(tenant_id="../etc", size_bytes=1024)
        assert result.allowed is False
        assert "invalid" in (result.reason or "")


class TestQuotaRecordWithoutRedis:
    """Tests for record_* operations without Redis (no-op)."""

    async def test_record_upload_noop(self) -> None:
        mgr = TenantFileQuotaManager(redis_client=None)
        assert await mgr.record_upload("acme", 1024) is False

    async def test_record_delete_noop(self) -> None:
        mgr = TenantFileQuotaManager(redis_client=None)
        assert await mgr.record_delete("acme", 1024) is False


class TestQuotaGetUsageWithoutRedis:
    """Tests for :meth:`get_usage` without Redis (returns zeros)."""

    async def test_get_usage_zero(self) -> None:
        mgr = TenantFileQuotaManager(redis_client=None)
        usage = await mgr.get_usage("acme")
        assert usage == {"files": 0, "bytes": 0}


class TestQuotaResetWithoutRedis:
    """Tests for :meth:`reset_tenant` without Redis (no-op)."""

    async def test_reset_tenant_noop(self) -> None:
        mgr = TenantFileQuotaManager(redis_client=None)
        assert await mgr.reset_tenant("acme") is False


class TestQuotaCheckResult:
    """Tests for :class:`QuotaCheckResult` serialization."""

    def test_to_dict_allowed(self) -> None:
        result = QuotaCheckResult(allowed=True, current_files=5, current_bytes=1024)
        d = result.to_dict()
        assert d["allowed"] is True
        assert d["reason"] is None
        assert d["current_files"] == 5

    def test_to_dict_denied(self) -> None:
        result = QuotaCheckResult(
            allowed=False,
            reason="over limit",
            current_files=100,
            limit_files=50,
        )
        d = result.to_dict()
        assert d["allowed"] is False
        assert d["reason"] == "over limit"
        assert d["limit_files"] == 50
