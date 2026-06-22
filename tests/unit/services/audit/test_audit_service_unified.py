"""Тесты unified AuditService facade (Sprint 16 Wave 8, CP-20)."""

# ruff: noqa: S101

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.backend.core.audit.facade.audit_service import (
    AuditService,
    get_unified_audit_service,
)
from src.backend.services.audit.clickhouse_audit_service import AuditEvent


@pytest.mark.asyncio
async def test_emit_translates_to_audit_event_for_backend() -> None:
    """emit() конвертирует параметры в AuditEvent для ClickHouseAuditService."""
    backend = AsyncMock()
    service = AuditService(clickhouse_service=backend)

    await service.emit(
        event="feature.toggled",
        actor="user:alice",
        resource="feature_flag/ai_workspace_ttl",
        action="toggle",
        outcome="success",
        tenant_id="tenant-42",
        details={"old": False, "new": True},
    )

    backend.emit.assert_awaited_once()
    sent: AuditEvent = backend.emit.await_args.args[0]
    assert sent.event_type == "feature.toggled"
    assert sent.tenant_id == "tenant-42"
    # actor с префиксом "user:" попадает в user_id.
    assert sent.user_id == "user:alice"
    assert sent.payload["actor"] == "user:alice"
    assert sent.payload["resource"] == "feature_flag/ai_workspace_ttl"
    assert sent.payload["action"] == "toggle"
    assert sent.payload["outcome"] == "success"
    assert sent.payload["details"] == {"old": False, "new": True}


@pytest.mark.asyncio
async def test_emit_uses_correlation_id_from_contextvar() -> None:
    """correlation_id берётся из contextvar если не задан явно."""
    from src.backend.infrastructure.observability.correlation import correlation_id_var

    backend = AsyncMock()
    service = AuditService(clickhouse_service=backend)

    token = correlation_id_var.set("corr-abc-123")
    try:
        await service.emit(event="waf.denied", actor="plugin:credit_pipeline")
    finally:
        correlation_id_var.reset(token)

    sent: AuditEvent = backend.emit.await_args.args[0]
    assert sent.payload["correlation_id"] == "corr-abc-123"


@pytest.mark.asyncio
async def test_emit_explicit_correlation_id_overrides_contextvar() -> None:
    """Явный correlation_id перекрывает значение из contextvar."""
    from src.backend.infrastructure.observability.correlation import correlation_id_var

    backend = AsyncMock()
    service = AuditService(clickhouse_service=backend)

    token = correlation_id_var.set("corr-from-ctx")
    try:
        await service.emit(event="capability.granted", correlation_id="corr-explicit")
    finally:
        correlation_id_var.reset(token)

    sent: AuditEvent = backend.emit.await_args.args[0]
    assert sent.payload["correlation_id"] == "corr-explicit"


@pytest.mark.asyncio
async def test_emit_never_raises_when_backend_fails() -> None:
    """Backend exception → emit() возвращается без re-raise (audit не ломает биз-логику)."""
    backend = AsyncMock()
    backend.emit.side_effect = RuntimeError("clickhouse недоступен")

    service = AuditService(clickhouse_service=backend)
    # Должно вернуться без exception.
    await service.emit(event="boom", outcome="failure")
    backend.emit.assert_awaited_once()


@pytest.mark.asyncio
async def test_emit_default_outcome_and_severity() -> None:
    """outcome=success и severity=info — дефолты."""
    backend = AsyncMock()
    service = AuditService(clickhouse_service=backend)

    await service.emit(event="audit.test")

    sent: AuditEvent = backend.emit.await_args.args[0]
    assert sent.payload["outcome"] == "success"
    assert sent.severity == "info"


@pytest.mark.asyncio
async def test_emit_propagates_tenant_id_from_context() -> None:
    """tenant_id из TenantContext.current если не задан явно."""
    from src.backend.core.tenancy import TenantContext, tenant_scope

    backend = AsyncMock()
    service = AuditService(clickhouse_service=backend)
    ctx = TenantContext(tenant_id="t-from-context")

    with tenant_scope(ctx):
        await service.emit(event="audit.tenant_test")

    sent: AuditEvent = backend.emit.await_args.args[0]
    assert sent.tenant_id == "t-from-context"


def test_singleton_returns_same_instance() -> None:
    """get_unified_audit_service() возвращает singleton."""
    a = get_unified_audit_service()
    b = get_unified_audit_service()
    assert a is b
