# ruff: noqa: S101
"""Тесты fallback в ``StepAuditMiddleware.track_step`` на ContextVar (S17 K3 W3 D12).

Покрывают:

* пустой ``correlation_id`` / ``tenant_id`` args + установленные ContextVar →
  audit-event получает значения из ContextVar;
* явный ``correlation_id`` / ``tenant_id`` args → перекрывают ContextVar;
* пустые args + пустые ContextVar → audit-event получает пустые строки.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.core.config.features import feature_flags
from src.backend.infrastructure.observability.correlation import (
    correlation_id_var,
    set_correlation_context,
    tenant_id_var,
)
from src.backend.infrastructure.workflow.middlewares.step_audit import (
    StepAuditMiddleware,
)


@pytest.fixture(autouse=True)
def _enable_step_log(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "workflow_step_log_enabled", True)


@pytest.fixture(autouse=True)
def _reset_correlation_vars() -> None:
    correlation_id_var.set("")
    tenant_id_var.set("")


def _make_middleware() -> StepAuditMiddleware:
    fake_client = MagicMock()
    fake_client.insert = AsyncMock()
    return StepAuditMiddleware(clickhouse_client=fake_client, batch_size=10)


@pytest.mark.asyncio
async def test_track_step_pulls_correlation_id_from_context_var() -> None:
    """Пустой arg + set_correlation_context → event берёт значение из ContextVar."""
    set_correlation_context(correlation_id="cid-from-context", tenant_id="tnt-1")
    mw = _make_middleware()
    await mw.start()
    try:
        async with mw.track_step(workflow_id="wf-1", step_name="step-a"):
            pass
        event = mw._buffer[0]
        assert event.correlation_id == "cid-from-context"
        assert event.tenant_id == "tnt-1"
    finally:
        await mw.stop()


@pytest.mark.asyncio
async def test_explicit_arg_overrides_context_var() -> None:
    """Явный ``correlation_id`` arg перекрывает ContextVar."""
    set_correlation_context(correlation_id="cid-from-context", tenant_id="tnt-context")
    mw = _make_middleware()
    await mw.start()
    try:
        async with mw.track_step(
            workflow_id="wf-2",
            step_name="step-b",
            correlation_id="cid-explicit",
            tenant_id="tnt-explicit",
        ):
            pass
        event = mw._buffer[0]
        assert event.correlation_id == "cid-explicit"
        assert event.tenant_id == "tnt-explicit"
    finally:
        await mw.stop()


@pytest.mark.asyncio
async def test_no_context_no_arg_yields_empty_strings() -> None:
    """Без аргументов и без ContextVar → пустые строки в audit-event."""
    mw = _make_middleware()
    await mw.start()
    try:
        async with mw.track_step(workflow_id="wf-3", step_name="step-c"):
            pass
        event = mw._buffer[0]
        assert event.correlation_id == ""
        assert event.tenant_id == ""
    finally:
        await mw.stop()
