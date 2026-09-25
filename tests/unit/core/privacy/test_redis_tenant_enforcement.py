"""Regression tests для Privacy Redis adapter tenant-awareness (Option A, ADR-0345).

Per v4 §10 P1 '0 importers + migration window + contract test':
contract tests verify fail-closed behavior в ``RedisErasureAdapter``.

Cycle 158+ Privacy investigation (commit ca9fa600c) found that
``RedisErasureAdapter`` uses ``subject_id`` only (NO ``current_tenant()``).
Per ADR-0345/v5 prompt Option A: added ``explicit_tenant_id`` parameter +
``get_tenant_id()`` fallback для tenant-awareness.

Per v4 §3 evidence-first: NOT estimates, ACTUAL behavior verified.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.core.privacy.delete_data_subject._redis import RedisErasureAdapter
from src.backend.core.privacy.delete_data_subject._types import (
    ErasureResultStatus,
    ErasureStrategy,
)


@pytest.mark.asyncio
class TestRedisTenantEnforcement:
    """Per ADR-0345 Option A: tenant-awareness per-call enforcement."""

    async def test_legacy_path_without_tenant_context(self) -> None:
        """Без explicit_tenant_id и без TenantContext → legacy behavior.

        Per v4 §10 P1 backwards-compat: existing callers без TenantContext
        setup continue working (no breaking change).
        """
        from src.backend.core.tenancy import _current

        try:
            _current.set(None)
        except Exception:
            pass

        redis_mock = MagicMock()
        scan_calls_log: list = []

        async def _scan_log(cursor: int = 0, match: str = "", count: int = 100):
            scan_calls_log.append(match)
            return (0, [])

        redis_mock.scan = AsyncMock(side_effect=_scan_log)
        redis_mock.unlink = AsyncMock(return_value=0)

        adapter = RedisErasureAdapter(redis_client=redis_mock)
        await adapter.execute(
            subject_id="user:42",
            subject_type="user",
            strategy=ErasureStrategy.ANONYMIZE,
            correlation_id="test",
        )

        # SCAN was called with ONLY DEFAULT prefixes (no tenant-id pattern).
        # Note: ``tenant:`` IS in DEFAULT_PREFIXES (separate from tenant-id filter).
        # Tenant-id filter pattern is ``tenant:<id>:user:42`` (with colon after id).
        assert not any("tenant:t-a:" in call for call in scan_calls_log), (
            f"Legacy path should NOT add tenant-id prefix; got: {scan_calls_log}"
        )

    async def test_explicit_tenant_id_filters_by_tenant(self) -> None:
        """Explicit ``explicit_tenant_id`` → SCAN pattern restricted by tenant.

        Per v4 §10 P1: cross-tenant access prevented.
        """
        redis_mock = MagicMock()
        redis_mock.scan = AsyncMock(return_value=(0, []))
        redis_mock.unlink = AsyncMock(return_value=0)

        adapter = RedisErasureAdapter(redis_client=redis_mock)
        await adapter.execute(
            subject_id="user:42",
            subject_type="user",
            strategy=ErasureStrategy.ANONYMIZE,
            correlation_id="test",
            explicit_tenant_id="t-a",
        )

        # SCAN was called with EXTRA tenant prefix.
        scan_calls = redis_mock.scan.call_args_list
        assert any("tenant:t-a:" in str(call) for call in scan_calls), (
            "Explicit tenant should add tenant prefix to SCAN"
        )

    async def test_tenant_context_filters_by_tenant(self) -> None:
        """``current_tenant()`` from TenantContext → SCAN restricted by tenant.

        Per v4 §10 P1: cross-tenant access prevented via TenantContext.
        """
        from src.backend.core.tenancy import TenantContext, set_tenant

        redis_mock = MagicMock()
        redis_mock.scan = AsyncMock(return_value=(0, []))
        redis_mock.unlink = AsyncMock(return_value=0)

        set_tenant(TenantContext(tenant_id="t-b", plan="pro", region="ru"))

        adapter = RedisErasureAdapter(redis_client=redis_mock)
        await adapter.execute(
            subject_id="user:42",
            subject_type="user",
            strategy=ErasureStrategy.ANONYMIZE,
            correlation_id="test",
        )

        scan_calls = redis_mock.scan.call_args_list
        assert any("tenant:t-b:" in str(call) for call in scan_calls), (
            "TenantContext should add tenant prefix to SCAN"
        )

    async def test_explicit_param_overrides_context(self) -> None:
        """Explicit ``explicit_tenant_id`` param takes priority over TenantContext.

        Per ADR-0345: explicit caller intent is more authoritative.
        """
        from src.backend.core.tenancy import TenantContext, set_tenant

        redis_mock = MagicMock()
        redis_mock.scan = AsyncMock(return_value=(0, []))
        redis_mock.unlink = AsyncMock(return_value=0)

        # Caller context = t-a, but explicit param = t-b → uses t-b.
        set_tenant(TenantContext(tenant_id="t-a", plan="pro", region="ru"))

        adapter = RedisErasureAdapter(redis_client=redis_mock)
        await adapter.execute(
            subject_id="user:42",
            subject_type="user",
            strategy=ErasureStrategy.ANONYMIZE,
            correlation_id="test",
            explicit_tenant_id="t-b",
        )

        scan_calls = redis_mock.scan.call_args_list
        assert any("tenant:t-b:" in str(call) for call in scan_calls), (
            "Explicit param should take priority over TenantContext"
        )
        assert not any("tenant:t-a:" in str(call) for call in scan_calls), (
            "TenantContext value should NOT be used when explicit param set"
        )

    async def test_no_redis_client_returns_skipped(self) -> None:
        """No redis client configured → SKIPPED status (legacy safety)."""
        adapter = RedisErasureAdapter(redis_client=None)
        result = await adapter.execute(
            subject_id="user:42",
            subject_type="user",
            strategy=ErasureStrategy.ANONYMIZE,
            correlation_id="test",
        )
        assert result.status == ErasureResultStatus.SKIPPED
