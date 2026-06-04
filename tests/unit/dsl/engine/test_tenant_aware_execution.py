# ruff: noqa: S101
"""K-ARCH-4 (S17): ExecutionEngine tenant_aware enforcement.

Pipeline с ``tenant_aware=True`` обязан валиться с
:class:`TenantContextRequiredError`, если ни RequestContext, ни
TenantContext не содержат непустой tenant_id. И наоборот — должен
успешно выполняться, если tenant_id установлен хотя бы в одном
из источников.
"""

from __future__ import annotations

import pytest

from src.backend.core.errors import TenantContextRequiredError
from src.backend.core.request_context import (
    RequestContext,
    bind_request_context,
    clear_request_context,
)
from src.backend.core.tenancy import TenantContext, tenant_scope
from src.backend.dsl.engine.exchange import ExchangeStatus
from src.backend.dsl.engine.execution_engine import ExecutionEngine
from src.backend.dsl.engine.pipeline import Pipeline


def _empty_pipeline(*, tenant_aware: bool = False) -> Pipeline:
    """Минимальный pipeline без процессоров (для проверки gate)."""
    return Pipeline(
        route_id="r_tenant_test", source="internal:test", tenant_aware=tenant_aware
    )


class TestTenantAwareGate:
    """ExecutionEngine._check_tenant_aware — runtime invariant."""

    async def test_non_tenant_aware_passes_without_context(self) -> None:
        """``tenant_aware=False`` — gate не активируется, pipeline пройдёт."""
        engine = ExecutionEngine(validate_before_execute=False)
        pipeline = _empty_pipeline(tenant_aware=False)
        result = await engine.execute(pipeline, body={"x": 1})
        assert result.status == ExchangeStatus.completed
        assert result.meta.tenant_id is None

    async def test_tenant_aware_fails_without_any_context(self) -> None:
        """``tenant_aware=True`` без context'ов → TenantContextRequiredError."""
        engine = ExecutionEngine(validate_before_execute=False)
        pipeline = _empty_pipeline(tenant_aware=True)
        with pytest.raises(TenantContextRequiredError) as exc_info:
            await engine.execute(pipeline, body={})
        assert exc_info.value.route_id == "r_tenant_test"

    async def test_tenant_aware_passes_with_request_context(self) -> None:
        """tenant_id в RequestContext активирует pipeline."""
        engine = ExecutionEngine(validate_before_execute=False)
        pipeline = _empty_pipeline(tenant_aware=True)
        ctx = RequestContext(
            correlation_id="cid-1",
            request_id="rid-1",
            method="POST",
            path="/api/v1/x",
            tenant_id="tenant-A",
        )
        token = bind_request_context(ctx)
        try:
            result = await engine.execute(pipeline, body={})
        finally:
            clear_request_context(token)
        assert result.status == ExchangeStatus.completed
        assert result.meta.tenant_id == "tenant-A"
        assert result.properties.get("tenant_id") == "tenant-A"

    async def test_tenant_aware_passes_with_tenant_context(self) -> None:
        """tenant_id в TenantContext (без RequestContext) тоже валиден."""
        engine = ExecutionEngine(validate_before_execute=False)
        pipeline = _empty_pipeline(tenant_aware=True)
        with tenant_scope(TenantContext(tenant_id="tenant-B")):
            result = await engine.execute(pipeline, body={})
        assert result.status == ExchangeStatus.completed
        assert result.meta.tenant_id == "tenant-B"

    async def test_tenant_aware_isolation_between_tenants(self) -> None:
        """Два запуска под разными tenant_id не утекают друг в друга."""
        engine = ExecutionEngine(validate_before_execute=False)
        pipeline = _empty_pipeline(tenant_aware=True)
        with tenant_scope(TenantContext(tenant_id="tenant-A")):
            r_a = await engine.execute(pipeline, body={"order": 1})
        with tenant_scope(TenantContext(tenant_id="tenant-B")):
            r_b = await engine.execute(pipeline, body={"order": 2})
        assert r_a.meta.tenant_id == "tenant-A"
        assert r_b.meta.tenant_id == "tenant-B"
        assert r_a.meta.tenant_id != r_b.meta.tenant_id

    async def test_request_context_overrides_empty_tenant_context(self) -> None:
        """RequestContext.tenant_id используется первой (приоритетнее)."""
        engine = ExecutionEngine(validate_before_execute=False)
        pipeline = _empty_pipeline(tenant_aware=True)
        ctx = RequestContext(
            correlation_id="cid-2",
            request_id="rid-2",
            method="GET",
            path="/x",
            tenant_id="from-request",
        )
        token = bind_request_context(ctx)
        try:
            with tenant_scope(TenantContext(tenant_id="from-tenant-ctx")):
                result = await engine.execute(pipeline, body={})
        finally:
            clear_request_context(token)
        assert result.meta.tenant_id == "from-request"
